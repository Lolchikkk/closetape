import os, re, uuid, json, math, wave, zipfile, shutil, subprocess, threading, array
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(os.getenv("DATA_DIR", str(Path.home() / "Closetape" / "jobs")))
ROOT.mkdir(parents=True, exist_ok=True)
APP_DIR = Path(getattr(__import__("sys"), "_MEIPASS", Path(__file__).resolve().parent.parent))
JOBS = {}
JOB_SLOT = threading.BoundedSemaphore(1)
app = FastAPI(title="Closetape ClipMaker", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["*"])

class JobRequest(BaseModel):
    url: str
    limit: int = Field(default=10, ge=1, le=20)
    transcribe: bool = False

def tool_path(name):
    exe = name + (".exe" if os.name == "nt" else "")
    candidates = [Path(os.getenv("CLOSETAPE_BIN_DIR", "")) / exe, APP_DIR / "tools" / exe, APP_DIR / exe]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return name

def run(cmd, timeout=None):
    args = list(cmd)
    if args and args[0] in {"ffmpeg", "ffprobe", "yt-dlp"}:
        args[0] = tool_path(args[0])
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)

def valid_vod(url):
    p = urlparse(url)
    return p.scheme == "https" and p.hostname in {"twitch.tv","www.twitch.tv","m.twitch.tv"} and re.fullmatch(r"/videos/\d+/?", p.path) is not None

def label(seconds):
    return str(timedelta(seconds=max(0,int(seconds)))) if seconds >= 3600 else str(timedelta(seconds=max(0,int(seconds))))[2:]

def audio_energy(video, work):
    wav = work / "audio.wav"
    vals = []
    try:
        run(["ffmpeg","-nostdin","-loglevel","error","-threads","1","-filter_threads","1","-y","-i",str(video),"-vn","-ac","1","-ar","16000","-f","wav",str(wav)], timeout=7200)
        with wave.open(str(wav), "rb") as f:
            rate = f.getframerate()
            position = 0
            while True:
                raw = f.readframes(rate * 5)
                if not raw: break
                samples = array.array("h")
                samples.frombytes(raw)
                if samples:
                    rms = math.sqrt(sum(x*x for x in samples) / len(samples))
                    vals.append((position / rate, rms))
                position += len(samples)
        return vals
    finally:
        wav.unlink(missing_ok=True)

def detect(video, work, want_transcript, limit, job_id):
    energy = audio_energy(video, work)
    duration = max((t for t,_ in energy), default=0) + 5
    transcript = []
    model_name = os.getenv("FASTER_WHISPER_MODEL", "")
    if want_transcript and model_name:
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(str(video), vad_filter=True)
            transcript = [{"start":s.start,"end":s.end,"text":s.text.strip()} for s in segments]
        except Exception:
            JOBS[job_id]["message"] = "Распознавание речи недоступно; ищем пики звука"
    ranked = []
    if transcript:
        words = re.compile(r"\b(вау|нет|что|ах|ого|жесть|давай|боже|смешно|лол|победа|убил|клатч|nice|wow|no|what|oh|lol|insane|crazy|win|clutch|omg)\b", re.I)
        for s in transcript:
            center = (s["start"] + s["end"]) / 2
            sound = max((v for t,v in energy if abs(t-center)<12), default=0)
            score = len(words.findall(s["text"]))*2.8 + (1.2 if "!" in s["text"] else 0) + min(sound/7000,3)
            ranked.append((score, max(0,s["start"]-18), min(duration,s["end"]+22), s["text"]))
    else:
        ranked = [(v,t-20,t+25,"Громкий / динамичный момент") for t,v in energy]
    ranked.sort(reverse=True)
    chosen = []
    for score,start,end,title in ranked:
        start=max(0,start); end=min(duration,end)
        if end-start<8: continue
        if all(abs(start,x[0])>35 for x in chosen):
            chosen.append((start,end,title,score))
        if len(chosen)>=limit: break
    if not chosen:
        chosen=[(max(0,t-15),min(duration,t+25),"Фрагмент записи",v) for t,v in energy[:limit]]
    return sorted(chosen)

def process(job_id, req):
    job=JOBS[job_id]; work=ROOT/job_id
    try:
        work.mkdir(parents=True,exist_ok=True)
        job.update(status="downloading",progress=8,message="Скачиваем доступный Twitch VOD…")
        source=work/"source.mp4"
        command=["yt-dlp","--no-warnings","--no-progress","--no-playlist","--format","bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]","--merge-output-format","mp4","-o",str(work/"source.%(ext)s")]
        ffmpeg_dir=os.getenv("CLOSETAPE_BIN_DIR","")
        if ffmpeg_dir: command += ["--ffmpeg-location",ffmpeg_dir]
        command += [req.url]
        run(command,timeout=14400)
        found=[p for p in work.glob("source.*") if p.suffix.lower() in {".mp4",".mkv",".webm"}]
        if not found: raise RuntimeError("yt-dlp не вернул видеофайл")
        source=found[0]
        probe=json.loads(run(["ffprobe","-v","quiet","-show_format","-of","json",str(source)]).stdout)
        duration=float(probe["format"]["duration"])
        if duration<10: raise RuntimeError("Запись слишком короткая")
        job.update(status="analyzing",progress=28,message="Анализируем звук…")
        clips=detect(source,work,req.transcribe,req.limit,job_id)
        job.update(status="exporting",progress=62,message="Экспортируем MP4-клипы…")
        output=work/"clips"; output.mkdir(exist_ok=True); items=[]
        for i,(start,end,title,score) in enumerate(clips,1):
            dest=output/f"closetape_{i:02d}.mp4"
            run(["ffmpeg","-nostdin","-loglevel","error","-threads","1","-filter_threads","1","-y","-ss",str(start),"-i",str(source),"-t",str(end-start),"-map","0:v:0","-map","0:a?","-vf","scale=w=min(1920\\,iw):h=min(1080\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2","-c:v","libx264","-preset","veryfast","-crf","23","-threads","1","-c:a","aac","-b:a","160k","-movflags","+faststart",str(dest)],timeout=3600)
            items.append({"title":title[:100],"start":start,"end":end,"start_label":label(start),"end_label":label(end),"duration":label(end-start),"file":dest.name,"download_url":f"/api/jobs/{job_id}/clips/{dest.name}"})
        archive=work/"closetape_clips.zip"
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            for p in output.glob("*.mp4"): z.write(p,p.name)
        job.update(status="done",progress=100,message="Готово",clips=items,zip_url=f"/api/jobs/{job_id}/zip")
    except Exception as e:
        print(f"Closetape job {job_id} failed: {type(e).__name__}: {e}",flush=True)
        job.update(status="error",progress=100,message="Обработка остановлена",error=str(e)[:500])
    finally:
        JOB_SLOT.release()

@app.get("/")
def home():
    index = APP_DIR / "index.html"
    if not index.exists(): raise HTTPException(404,"Интерфейс не найден")
    return HTMLResponse(index.read_text(encoding="utf-8"))

@app.get("/api/health")
def health(): return {"ok":True,"service":"Closetape Desktop"}

@app.post("/api/jobs")
def create_job(req: JobRequest):
    if not valid_vod(req.url): raise HTTPException(400,"Нужна прямая HTTPS-ссылка Twitch вида https://www.twitch.tv/videos/123456")
    if not JOB_SLOT.acquire(blocking=False): raise HTTPException(429,"Уже обрабатывается другой стрим. Дождитесь завершения.")
    job_id=uuid.uuid4().hex
    JOBS[job_id]={"id":job_id,"status":"queued","progress":2,"message":"Задача создана","clips":[]}
    try: threading.Thread(target=process,args=(job_id,req),daemon=True).start()
    except Exception:
        JOB_SLOT.release(); JOBS.pop(job_id,None); raise
    return {"id":job_id,"status":"queued"}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Задача не найдена")
    return {k:v for k,v in job.items() if k!="error"} | ({"error":job["error"]} if job.get("error") else {})

@app.get("/api/jobs/{job_id}/clips/{filename}")
def get_clip(job_id: str,filename: str):
    if not re.fullmatch(r"closetape_\d+\.mp4",filename): raise HTTPException(400,"Недопустимое имя файла")
    path=ROOT/job_id/"clips"/filename
    if not path.is_file(): raise HTTPException(404,"Клип не найден")
    return FileResponse(path,media_type="video/mp4",filename=filename)

@app.get("/api/jobs/{job_id}/zip")
def get_zip(job_id: str):
    path=ROOT/job_id/"closetape_clips.zip"
    if not path.is_file(): raise HTTPException(404,"Архив ещё не готов")
    return FileResponse(path,media_type="application/zip",filename="closetape_clips.zip")
