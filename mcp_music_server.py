#!/usr/bin/env python3
"""
Music Recognition + Spotify MCP Server
Ses dosyalarını tanıyıp Spotify'a ekleyen MCP server
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
import httpx
import json
import base64
import hashlib
import hmac
import time
import os
import tempfile
from typing import Optional, List, Dict, Any
import logging
from urllib.parse import urlencode
from pathlib import Path
from starlette.responses import RedirectResponse, JSONResponse
import secrets

# Environment variables için
try:
    from dotenv import load_dotenv
    load_dotenv()  # .env dosyasını yükle
    DOTENV_AVAILABLE = True
    logger.info(".env dosyası yüklendi")
except ImportError:
    DOTENV_AVAILABLE = False
    logger.warning("python-dotenv yüklenemedi, environment variables manuel ayarlanmalı")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Audio processing için
try:
    from pydub import AudioSegment
    AUDIO_PROCESSING_AVAILABLE = True
    logger.info("pydub yüklendi, ses kırpma aktif")
except ImportError:
    AUDIO_PROCESSING_AVAILABLE = False
    logger.warning("pydub yüklenemedi, ses kırpma deaktif")

# FastAPI app
app = FastAPI(
    title="Music Recognition + Spotify MCP Server",
    description="Ses dosyalarını tanıyıp Spotify'a ekleyen MCP server",
    version="1.0.0"
)

# MCP Tool Names
class MusicMCPTools(str, Enum):
    UPLOAD_AUDIO = "upload_audio"
    RECOGNIZE_MUSIC = "recognize_music"
    SEARCH_SPOTIFY = "search_spotify"
    ADD_TO_LIKED = "add_to_liked_songs"
    CREATE_PLAYLIST = "create_playlist"
    ADD_TO_PLAYLIST = "add_to_playlist"
    GET_USER_PROFILE = "get_user_profile"
    GET_PLAYLISTS = "get_playlists"

# Request/Response Models
class ToolCallRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}

class ToolCallResponse(BaseModel):
    result: Dict[str, Any]
    success: bool = True
    timestamp: str
    service_used: str

# Server state
server_state = {
    "name": "Music Recognition + Spotify MCP Server",
    "version": "1.0.0",
    "services": {
        "music_recognition": "ACRCloud API",
        "spotify": "Spotify Web API"
    },
    "requests_count": 0,
    "errors_count": 0,
    "recognized_songs": 0,
    "spotify_actions": 0,
    "tools": [],
    "resources": [],
    "temp_files": [],
    "start_time": datetime.now().isoformat()
}

# API Keys (Environment variables'dan alınacak)
ACRCLOUD_CONFIG = {
    "host": os.getenv("ACRCLOUD_HOST", "identify-eu-west-1.acrcloud.com"),
    "access_key": os.getenv("ACRCLOUD_ACCESS_KEY", "demo_access_key"),
    "access_secret": os.getenv("ACRCLOUD_ACCESS_SECRET", "demo_secret"),
    "timeout": 30  # ACRCloud için uzun timeout
}

SPOTIFY_CONFIG = {
    "client_id": os.getenv("SPOTIFY_CLIENT_ID", "demo_client_id"),
    "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", "demo_secret"),
    "redirect_uri": os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8002/callback"),
    "access_token": None,
    "refresh_token": None,
    "token_expires_at": 0,
    "is_user_token": False,
    "scopes": "user-read-email user-read-private user-library-modify playlist-modify-private playlist-modify-public"
}

# HTTP Client
http_client = httpx.AsyncClient(timeout=30.0)

# Basit state takibi (demo amaçlı bellek içi)
oauth_state_store: Dict[str, float] = {}

# Config yükleme
def load_local_config() -> None:
    """music_mcp/config.json varsa Spotify/ACRCloud ayarlarını yükler"""
    try:
        config_path = Path(__file__).parent / "config.json"
        logger.info(f"Config yolu: {config_path}")
        if not config_path.exists():
            logger.warning("config.json bulunamadı")
            return
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Config yüklendi: {list(data.keys())}")
        
        # Spotify
        sp = data.get("spotify", {})
        if sp.get("client_id"):
            SPOTIFY_CONFIG["client_id"] = sp["client_id"]
            logger.info(f"Spotify client_id yüklendi: {sp['client_id'][:10]}...")
        if sp.get("client_secret"):
            SPOTIFY_CONFIG["client_secret"] = sp["client_secret"]
        if sp.get("redirect_uri"):
            SPOTIFY_CONFIG["redirect_uri"] = sp["redirect_uri"]
            
        # ACRCloud
        ac = data.get("acrcloud", {})
        if ac.get("host"):
            ACRCLOUD_CONFIG["host"] = ac["host"]
        if ac.get("access_key"):
            ACRCLOUD_CONFIG["access_key"] = ac["access_key"]
            logger.info(f"ACRCloud access_key yüklendi: {ac['access_key'][:10]}...")
        if ac.get("access_secret"):
            ACRCLOUD_CONFIG["access_secret"] = ac["access_secret"]
    except Exception as e:
        logger.error(f"Yerel config okunamadı: {e}")

@app.on_event("startup")
async def startup_event():
    """Server başlatma"""
    logger.info(">> Music Recognition + Spotify MCP Server başlatılıyor...")
    # Yerel config yükle
    load_local_config()
    
    # Tools listesi
    server_state["tools"] = [
        {
            "name": MusicMCPTools.UPLOAD_AUDIO,
            "description": "Ses dosyası yükler (MP3, WAV, M4A formatları)",
            "parameters": {
                "audio_file": {"type": "file", "description": "Ses dosyası", "required": True}
            }
        },
        {
            "name": MusicMCPTools.RECOGNIZE_MUSIC,
            "description": "Yüklenen ses dosyasındaki müziği tanır",
            "parameters": {
                "file_id": {"type": "string", "description": "Yüklenen dosya ID'si", "required": True}
            }
        },
        {
            "name": MusicMCPTools.SEARCH_SPOTIFY,
            "description": "Spotify'da şarkı arar",
            "parameters": {
                "query": {"type": "string", "description": "Arama terimi (şarkı adı, sanatçı)", "required": True},
                "type": {"type": "string", "description": "Arama tipi (track, artist, album)", "default": "track"}
            }
        },
        {
            "name": MusicMCPTools.ADD_TO_LIKED,
            "description": "Şarkıyı Spotify beğenilen şarkılara ekler",
            "parameters": {
                "track_id": {"type": "string", "description": "Spotify track ID'si", "required": True}
            }
        },
        {
            "name": MusicMCPTools.CREATE_PLAYLIST,
            "description": "Yeni Spotify playlist oluşturur",
            "parameters": {
                "name": {"type": "string", "description": "Playlist adı", "required": True},
                "description": {"type": "string", "description": "Playlist açıklaması", "default": "MCP ile oluşturuldu"}
            }
        },
        {
            "name": MusicMCPTools.ADD_TO_PLAYLIST,
            "description": "Şarkıyı belirtilen playlist'e ekler",
            "parameters": {
                "playlist_id": {"type": "string", "description": "Playlist ID'si", "required": True},
                "track_id": {"type": "string", "description": "Track ID'si", "required": True}
            }
        },
        {
            "name": MusicMCPTools.GET_USER_PROFILE,
            "description": "Kullanıcının Spotify profil bilgilerini getirir",
            "parameters": {}
        },
        {
            "name": MusicMCPTools.GET_PLAYLISTS,
            "description": "Kullanıcının Spotify playlist'lerini listeler",
            "parameters": {}
        }
    ]
    
    # Resources listesi
    server_state["resources"] = [
        {
            "uri": "music://recognition/history",
            "name": "Tanınan Şarkılar",
            "description": "Daha önce tanınan şarkıların geçmişi",
            "type": "recognition_history"
        },
        {
            "uri": "spotify://user/profile",
            "name": "Spotify Profili",
            "description": "Kullanıcının Spotify profil bilgileri",
            "type": "user_profile"
        },
        {
            "uri": "spotify://user/playlists",
            "name": "Spotify Playlist'leri",
            "description": "Kullanıcının tüm playlist'leri",
            "type": "playlist_collection"
        }
    ]
    
    logger.info(f"OK Music MCP Server hazır! {len(server_state['tools'])} tool, {len(server_state['resources'])} resource")

# ACRCloud signature fonksiyonu artık recognize_audio_acrcloud içinde

def trim_audio_for_recognition(audio_data: bytes, max_duration: int = 10) -> bytes:
    """Ses dosyasını müzik tanıma için kırp (ilk 10 saniye)"""
    logger.info(f"Ses kırpma başlıyor: {len(audio_data)} bytes -> {max_duration} saniye")
    
    if not AUDIO_PROCESSING_AVAILABLE:
        logger.warning("pydub yüklü değil, ses kırpma yapılamıyor - orijinal dosya kullanılacak")
        # pydub yoksa da en azından dosya boyutunu sınırla (ilk %10'unu al)
        if len(audio_data) > 1000000:  # 1MB'den büyükse
            trimmed_size = min(len(audio_data) // 10, 500000)  # %10'u veya max 500KB
            logger.info(f"pydub olmadan kırpma: {len(audio_data)} -> {trimmed_size} bytes")
            return audio_data[:trimmed_size]
        return audio_data
    
    try:
        # Temporary dosya oluştur
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_input:
            temp_input.write(audio_data)
            temp_input_path = temp_input.name
        
        # Audio segment yükle
        audio = AudioSegment.from_file(temp_input_path)
        logger.info(f"Audio yüklendi: {len(audio)}ms süre")
        
        # İlk max_duration saniyeyi al
        trimmed_audio = audio[:max_duration * 1000]  # milliseconds
        
        # Temporary output dosyası
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_output:
            temp_output_path = temp_output.name
        
        # Kırpılmış sesi kaydet
        trimmed_audio.export(temp_output_path, format="mp3", bitrate="128k")
        
        # Kırpılmış veriyi oku
        with open(temp_output_path, 'rb') as f:
            trimmed_data = f.read()
        
        # Temporary dosyaları sil
        os.unlink(temp_input_path)
        os.unlink(temp_output_path)
        
        logger.info(f"Ses başarıyla kırpıldı: {len(audio_data)} -> {len(trimmed_data)} bytes ({max_duration}s)")
        return trimmed_data
        
    except Exception as e:
        logger.error(f"Ses kırpma hatası: {e}")
        # Hata durumunda da dosya boyutunu sınırla
        if len(audio_data) > 1000000:  # 1MB'den büyükse
            trimmed_size = min(len(audio_data) // 5, 800000)  # %20'si veya max 800KB
            logger.info(f"Hata sonrası kırpma: {len(audio_data)} -> {trimmed_size} bytes")
            return audio_data[:trimmed_size]
        return audio_data

async def recognize_audio_acrcloud(audio_data: bytes) -> dict:
    """ACRCloud ile ses tanıma"""
    try:
        timestamp = str(int(time.time()))
        nonce = str(int(time.time() * 1000000))
        
        # ACRCloud signature için doğru string formatı
        string_to_sign = f"POST\n/v1/identify\n{ACRCLOUD_CONFIG['access_key']}\naudio\n1\n{timestamp}"
        signature = base64.b64encode(
            hmac.new(
                ACRCLOUD_CONFIG['access_secret'].encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')
        
        logger.info(f"ACRCloud signature string: {string_to_sign}")
        logger.info(f"ACRCloud signature: {signature[:20]}...")
        
        # Multipart form data
        files = {
            'sample': ('audio.mp3', audio_data, 'audio/mpeg'),
            'sample_bytes': (None, str(len(audio_data))),
            'access_key': (None, ACRCLOUD_CONFIG['access_key']),
            'data_type': (None, 'audio'),
            'timestamp': (None, timestamp),
            'signature': (None, signature),
            'signature_version': (None, '1')
        }
        
        url = f"https://{ACRCLOUD_CONFIG['host']}/v1/identify"
        
        # httpx multipart request
        logger.info(f"ACRCloud API'ye istek gönderiliyor: {url}")
        response = await http_client.post(url, files=files, timeout=ACRCLOUD_CONFIG['timeout'])
        
        if response.status_code == 200:
            result = response.json()
            status_msg = result.get('status', {}).get('msg', 'Success')
            logger.info(f"ACRCloud API başarılı: {status_msg}")
            
            # Sonuç detayını logla
            if result.get('metadata', {}).get('music'):
                music_count = len(result['metadata']['music'])
                logger.info(f"ACRCloud sonuç: {music_count} müzik bulundu")
            else:
                logger.warning("ACRCloud: Müzik bulunamadı (No result)")
                
            return result
        else:
            logger.error(f"ACRCloud API error: {response.status_code} - {response.text}")
            return {"status": {"code": -1, "msg": f"API Error: {response.status_code} - {response.text[:100]}"}}
            
    except Exception as e:
        error_msg = f"ACRCloud recognition error: {str(e)}"
        logger.error(error_msg)
        logger.error(f"ACRCloud config: host={ACRCLOUD_CONFIG['host']}, key_length={len(ACRCLOUD_CONFIG['access_key'])}")
        
        # Hata detayını incele
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        return {"status": {"code": -1, "msg": f"Recognition error: {str(e) if str(e) else 'Unknown error'}"}}

async def get_spotify_access_token() -> str:
    """Spotify access token al (Client Credentials flow)"""
    try:
        # Demo için basit client credentials flow
        # Gerçek uygulamada Authorization Code flow kullanılmalı
        
        auth_string = f"{SPOTIFY_CONFIG['client_id']}:{SPOTIFY_CONFIG['client_secret']}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'client_credentials'
        }
        
        response = await http_client.post(
            'https://accounts.spotify.com/api/token',
            headers=headers,
            data=data
        )
        
        if response.status_code == 200:
            token_data = response.json()
            SPOTIFY_CONFIG['access_token'] = token_data['access_token']
            SPOTIFY_CONFIG['token_expires_at'] = time.time() + token_data.get('expires_in', 3600) - 30
            SPOTIFY_CONFIG['is_user_token'] = False
            return token_data['access_token']
        else:
            logger.error(f"Spotify token error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Spotify token error: {str(e)}")
        return None

async def search_spotify_track(query: str, search_type: str = "track") -> dict:
    """Spotify'da şarkı ara"""
    try:
        # Token yoksa client credentials ile al
        if not SPOTIFY_CONFIG['access_token']:
            await get_spotify_access_token()
        
        if not SPOTIFY_CONFIG['access_token']:
            return {"error": "Spotify access token alınamadı"}
        
        headers = {
            'Authorization': f'Bearer {SPOTIFY_CONFIG["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        params = {
            'q': query,
            'type': search_type,
            'limit': 10
        }
        
        response = await http_client.get(
            'https://api.spotify.com/v1/search',
            headers=headers,
            params=params
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Spotify search error: {response.status_code} - {response.text}")
            return {"error": f"Spotify API error: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Spotify search error: {str(e)}")
        return {"error": str(e)}

@app.get("/")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "server": server_state["name"],
        "version": server_state["version"],
        "services": server_state["services"],
        "uptime_seconds": (datetime.now() - datetime.fromisoformat(server_state["start_time"])).total_seconds(),
        "stats": {
            "requests_count": server_state["requests_count"],
            "errors_count": server_state["errors_count"],
            "recognized_songs": server_state["recognized_songs"],
            "spotify_actions": server_state["spotify_actions"]
        }
    }

@app.get("/tools")
async def list_tools():
    """MCP Tools listesi"""
    server_state["requests_count"] += 1
    return {
        "tools": server_state["tools"],
        "count": len(server_state["tools"]),
        "server": server_state["name"]
    }

@app.get("/resources")
async def list_resources():
    """MCP Resources listesi"""
    server_state["requests_count"] += 1
    return {
        "resources": server_state["resources"],
        "count": len(server_state["resources"]),
        "server": server_state["name"]
    }

@app.get("/context")
async def get_context(resource_uri: Optional[str] = None):
    """MCP Context endpoint"""
    server_state["requests_count"] += 1
    
    context = {
        "server": server_state["name"],
        "description": "Ses dosyalarını tanıyıp Spotify'a ekleyen MCP server",
        "capabilities": [
            "audio_recognition",
            "music_identification", 
            "spotify_integration",
            "playlist_management",
            "liked_songs_management"
        ],
        "services": server_state["services"],
        "workflow": [
            "1. Ses dosyası yükle (upload_audio)",
            "2. Müziği tanı (recognize_music)", 
            "3. Spotify'da ara (search_spotify)",
            "4. Beğenilenlere ekle (add_to_liked)"
        ],
        "supported_formats": ["MP3", "WAV", "M4A", "FLAC"],
        "timestamp": datetime.now().isoformat()
    }
    
    if resource_uri:
        context["requested_resource"] = resource_uri
        
    return context

# =======================
# Spotify OAuth Akışı
# =======================

@app.get("/spotify/login")
async def spotify_login():
    """Kullanıcıyı Spotify OAuth sayfasına yönlendirir"""
    state = secrets.token_urlsafe(16)
    oauth_state_store[state] = time.time()
    params = {
        'client_id': SPOTIFY_CONFIG['client_id'],
        'response_type': 'code',
        'redirect_uri': SPOTIFY_CONFIG['redirect_uri'],
        'scope': SPOTIFY_CONFIG['scopes'],
        'state': state,
        'show_dialog': 'true'
    }
    url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
    return JSONResponse({"login_url": url, "note": "Bu URL'yi tarayıcıda açıp izin verin, ardından server /callback'i işleyecek."})


@app.get("/callback")
async def spotify_callback(code: Optional[str] = Query(None), state: Optional[str] = Query(None), error: Optional[str] = Query(None)):
    """Spotify OAuth callback - yetkilendirme kodunu access token'a çevirir"""
    if error:
        return JSONResponse({"success": False, "error": error}, status_code=400)
    if not code or not state:
        return JSONResponse({"success": False, "error": "Eksik code/state"}, status_code=400)
    if state not in oauth_state_store or time.time() - oauth_state_store[state] > 600:
        return JSONResponse({"success": False, "error": "Geçersiz/eskimiş state"}, status_code=400)

    # State'i tüket
    oauth_state_store.pop(state, None)

    auth_string = f"{SPOTIFY_CONFIG['client_id']}:{SPOTIFY_CONFIG['client_secret']}"
    auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
    headers = {
        'Authorization': f'Basic {auth_b64}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': SPOTIFY_CONFIG['redirect_uri']
    }
    resp = await http_client.post('https://accounts.spotify.com/api/token', headers=headers, data=data)
    if resp.status_code != 200:
        return JSONResponse({"success": False, "error": f"Token alınamadı: {resp.status_code}", "details": resp.text}, status_code=400)
    token_data = resp.json()
    SPOTIFY_CONFIG['access_token'] = token_data.get('access_token')
    SPOTIFY_CONFIG['refresh_token'] = token_data.get('refresh_token')
    SPOTIFY_CONFIG['token_expires_at'] = time.time() + token_data.get('expires_in', 3600) - 30
    SPOTIFY_CONFIG['is_user_token'] = True
    return JSONResponse({"success": True, "message": "Spotify bağlandı. Artık /tools/call ile kullanıcı işlemleri yapılabilir."})


async def ensure_spotify_user_token() -> bool:
    """Kullanıcı erişim token'ı var mı ve geçerli mi? Gerekirse yenile."""
    if SPOTIFY_CONFIG.get('is_user_token') and SPOTIFY_CONFIG.get('access_token'):
        if time.time() < SPOTIFY_CONFIG.get('token_expires_at', 0):
            return True
        # refresh
        if SPOTIFY_CONFIG.get('refresh_token'):
            auth_string = f"{SPOTIFY_CONFIG['client_id']}:{SPOTIFY_CONFIG['client_secret']}"
            auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
            headers = {
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': SPOTIFY_CONFIG['refresh_token']
            }
            resp = await http_client.post('https://accounts.spotify.com/api/token', headers=headers, data=data)
            if resp.status_code == 200:
                token_data = resp.json()
                SPOTIFY_CONFIG['access_token'] = token_data.get('access_token', SPOTIFY_CONFIG['access_token'])
                SPOTIFY_CONFIG['token_expires_at'] = time.time() + token_data.get('expires_in', 3600) - 30
                SPOTIFY_CONFIG['is_user_token'] = True
                return True
            else:
                logger.error(f"Spotify refresh error: {resp.status_code} - {resp.text}")
                return False
    return False


@app.get("/spotify/status")
async def spotify_status():
    return {
        "is_user_connected": bool(SPOTIFY_CONFIG.get('is_user_token') and SPOTIFY_CONFIG.get('access_token')),
        "expires_in_seconds": max(0, int(SPOTIFY_CONFIG.get('token_expires_at', 0) - time.time())),
        "scopes": SPOTIFY_CONFIG['scopes']
    }

@app.post("/upload")
async def upload_audio_file(file: UploadFile = File(...)):
    """Ses dosyası yükleme endpoint'i"""
    try:
        # Dosya formatı kontrolü
        allowed_formats = ['.mp3', '.wav', '.m4a', '.flac']
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_formats:
            raise HTTPException(
                status_code=400, 
                detail=f"Desteklenmeyen format: {file_ext}. Desteklenen: {', '.join(allowed_formats)}"
            )
        
        # Dosya boyutu kontrolü (max 10MB)
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Dosya boyutu 10MB'dan büyük olamaz")
        
        # Geçici dosya oluştur
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext)
        temp_file.write(content)
        temp_file.close()
        
        file_id = hashlib.md5(content).hexdigest()
        
        # Dosya bilgisini sakla
        server_state["temp_files"].append({
            "file_id": file_id,
            "original_name": file.filename,
            "temp_path": temp_file.name,
            "size": len(content),
            "format": file_ext,
            "upload_time": datetime.now().isoformat()
        })
        
        logger.info(f"Audio file uploaded: {file.filename} ({len(content)} bytes)")
        
        return {
            "success": True,
            "file_id": file_id,
            "filename": file.filename,
            "size": len(content),
            "format": file_ext,
            "message": "Ses dosyası başarıyla yüklendi"
        }
        
    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Dosya yükleme hatası: {str(e)}")

@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """MCP Tool çağrısı"""
    server_state["requests_count"] += 1
    
    try:
        tool_enum = MusicMCPTools(request.tool_name)
    except ValueError:
        server_state["errors_count"] += 1
        raise HTTPException(status_code=404, detail=f"Tool bulunamadı: {request.tool_name}")
    
    try:
        # Tool'a göre işlem yap
        if tool_enum == MusicMCPTools.RECOGNIZE_MUSIC:
            file_id = request.parameters.get("file_id")
            if not file_id:
                raise HTTPException(status_code=400, detail="file_id parametresi gerekli")
            
            # Dosyayı bul
            temp_file_info = None
            for f in server_state["temp_files"]:
                if f["file_id"] == file_id:
                    temp_file_info = f
                    break
            
            if not temp_file_info:
                raise HTTPException(status_code=404, detail=f"Dosya bulunamadı: {file_id}")
            
            # Ses dosyasını oku
            with open(temp_file_info["temp_path"], "rb") as f:
                audio_data = f.read()
            
            # Gerçek ACRCloud API ile müzik tanıma
            logger.info(f"Müzik tanıma başlatılıyor... Dosya boyutu: {len(audio_data)} bytes")
            
            # API key kontrolü
            if (ACRCLOUD_CONFIG['access_key'] in ["YOUR_ACR_KEY", "demo_access_key"] or 
                ACRCLOUD_CONFIG['access_secret'] in ["YOUR_ACR_SECRET", "demo_secret"]):
                # Demo veri döner eğer API key ayarlanmamışsa
                logger.warning("ACRCloud API keys ayarlanmamış, demo veri dönüyor")
                recognition_result = {
                    "status": {"code": 0, "msg": "Success (Demo Mode)"},
                    "metadata": {
                        "music": [{
                            "title": "Shape of You",
                            "artists": [{"name": "Ed Sheeran"}],
                            "album": {"name": "÷ (Divide)"},
                            "release_date": "2017-01-06",
                            "duration_ms": 233713,
                            "external_ids": {
                                "spotify": "7qiZfU4dY1lWllzX7mPBI3"
                            },
                            "score": 95
                        }]
                    }
                }
            else:
                # Ses dosyasını ACRCloud için kırp (10 saniye)
                trimmed_audio_data = trim_audio_for_recognition(audio_data, max_duration=10)
                
                # Gerçek API çağrısı
                recognition_result = await recognize_audio_acrcloud(trimmed_audio_data)
                logger.info(f"ACRCloud sonucu: {recognition_result.get('status', {}).get('msg', 'Unknown')}")
            
            server_state["recognized_songs"] += 1
            
            return ToolCallResponse(
                result={
                    "recognition": recognition_result,
                    "file_info": temp_file_info,
                    "success": recognition_result["status"]["code"] == 0
                },
                timestamp=datetime.now().isoformat(),
                service_used="ACRCloud API (Demo)"
            )
            
        elif tool_enum == MusicMCPTools.SEARCH_SPOTIFY:
            query = request.parameters.get("query")
            search_type = request.parameters.get("type", "track")
            
            if not query:
                raise HTTPException(status_code=400, detail="query parametresi gerekli")
            
            # Gerçek API çağrısı
            search_result = await search_spotify_track(query, search_type)
            if 'error' in search_result:
                raise HTTPException(status_code=502, detail=f"Spotify arama hatası: {search_result['error']}")
            return ToolCallResponse(
                result={
                    "search_query": query,
                    "search_type": search_type,
                    "results": search_result,
                    "found_tracks": len(search_result.get("tracks", {}).get("items", []))
                },
                timestamp=datetime.now().isoformat(),
                service_used="Spotify Web API"
            )
            
        elif tool_enum == MusicMCPTools.ADD_TO_LIKED:
            track_id = request.parameters.get("track_id")
            if not track_id:
                raise HTTPException(status_code=400, detail="track_id parametresi gerekli")
            
            # Kullanıcı token'ı gerekli
            if not await ensure_spotify_user_token():
                raise HTTPException(status_code=401, detail="Spotify kullanıcı girişi gerekli. /spotify/login ile yetkilendirin.")

            headers = {
                'Authorization': f'Bearer {SPOTIFY_CONFIG["access_token"]}',
                'Content-Type': 'application/json'
            }
            params = {
                'ids': track_id
            }
            resp = await http_client.put('https://api.spotify.com/v1/me/tracks', headers=headers, params=params)
            if resp.status_code in (200, 201):
                server_state["spotify_actions"] += 1
                return ToolCallResponse(
                    result={
                        "track_id": track_id,
                        "action": "added_to_liked_songs",
                        "success": True,
                        "message": "Şarkı beğenilen şarkılara eklendi"
                    },
                    timestamp=datetime.now().isoformat(),
                    service_used="Spotify Web API"
                )
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Spotify hata: {resp.text}")
            
        elif tool_enum == MusicMCPTools.GET_USER_PROFILE:
            if not await ensure_spotify_user_token():
                raise HTTPException(status_code=401, detail="Spotify kullanıcı girişi gerekli. /spotify/login ile yetkilendirin.")
            headers = {
                'Authorization': f'Bearer {SPOTIFY_CONFIG["access_token"]}'
            }
            resp = await http_client.get('https://api.spotify.com/v1/me', headers=headers)
            if resp.status_code == 200:
                profile = resp.json()
                return ToolCallResponse(
                    result={
                        "profile": profile,
                        "subscription": profile.get("product")
                    },
                    timestamp=datetime.now().isoformat(),
                    service_used="Spotify Web API"
                )
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Spotify hata: {resp.text}")
            
        elif tool_enum == MusicMCPTools.GET_PLAYLISTS:
            if not await ensure_spotify_user_token():
                raise HTTPException(status_code=401, detail="Spotify kullanıcı girişi gerekli. /spotify/login ile yetkilendirin.")
            headers = {
                'Authorization': f'Bearer {SPOTIFY_CONFIG["access_token"]}'
            }
            resp = await http_client.get('https://api.spotify.com/v1/me/playlists', headers=headers, params={'limit': 20})
            if resp.status_code == 200:
                playlists = resp.json()
                return ToolCallResponse(
                    result={
                        "playlists": playlists,
                        "total_playlists": playlists.get("total")
                    },
                    timestamp=datetime.now().isoformat(),
                    service_used="Spotify Web API"
                )
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"Spotify hata: {resp.text}")
            
        else:
            raise HTTPException(status_code=404, detail=f"Tool implementasyonu bulunamadı: {request.tool_name}")
            
    except Exception as e:
        server_state["errors_count"] += 1
        logger.error(f"Tool execution error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Tool çalıştırma hatası: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """Server kapatma - temp dosyaları temizle"""
    for file_info in server_state["temp_files"]:
        try:
            if os.path.exists(file_info["temp_path"]):
                os.unlink(file_info["temp_path"])
        except Exception as e:
            logger.error(f"Temp file cleanup error: {str(e)}")
    
    await http_client.aclose()
    logger.info(">> Music MCP Server kapatıldı")

if __name__ == "__main__":
    import uvicorn
    print(">> Music Recognition + Spotify MCP Server başlatılıyor...")
    print(">> Ses dosyalarını tanıyıp Spotify'a ekleyecek")
    print(">> http://127.0.0.1:8002 adresinde çalışacak")
    print()
    print("!! API KEY'leri environment variable olarak ayarlayın:")
    print("   - ACRCLOUD_ACCESS_KEY")
    print("   - ACRCLOUD_ACCESS_SECRET") 
    print("   - SPOTIFY_CLIENT_ID")
    print("   - SPOTIFY_CLIENT_SECRET")
    print()
    
    uvicorn.run(
        "mcp_music_server:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_level="info"
    )