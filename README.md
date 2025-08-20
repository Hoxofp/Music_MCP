# Music MCP Server 🎵

Ses dosyalarını tanıyıp Spotify'a ekleyen MCP (Model Context Protocol) server.

## Özellikler

- 🎵 Ses dosyası tanıma (ACRCloud API)
- 🎧 Spotify entegrasyonu
- 📱 RESTful API
- 🔒 Güvenli API anahtar yönetimi
- 📊 Test raporları

## Kurulum

### 1. Projeyi Klonlayın

```bash
git clone <repo-url>
cd music_mcp
```

### 2. Sanal Ortam Oluşturun

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# veya
venv\Scripts\activate     # Windows
```

### 3. Gereksinimleri Yükleyin

```bash
pip install -r requirements.txt
```

### 4. Environment Variables Ayarlayın

`.env.example` dosyasını `.env` olarak kopyalayın:

```bash
cp .env.example .env
```

`.env` dosyasını düzenleyerek API anahtarlarınızı ekleyin:

```env
# Spotify API Credentials
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8002/callback

# ACRCloud API Credentials
ACRCLOUD_HOST=identify-ap-southeast-1.acrcloud.com
ACRCLOUD_ACCESS_KEY=your_acrcloud_access_key_here
ACRCLOUD_ACCESS_SECRET=your_acrcloud_access_secret_here
```

## API Anahtarları Alma

### Spotify API

1. [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) adresine gidin
2. Yeni bir uygulama oluşturun
3. Client ID ve Client Secret'ı kopyalayın
4. Redirect URI olarak `http://127.0.0.1:8002/callback` ekleyin

### ACRCloud API

1. [ACRCloud Console](https://console.acrcloud.com) adresine gidin
2. Hesap oluşturun ve giriş yapın
3. Yeni bir proje oluşturun
4. Access Key ve Access Secret'ı kopyalayın

## Kullanım

### Server'ı Başlatma

```bash
python mcp_music_server.py
```

Server `http://127.0.0.1:8002` adresinde çalışacaktır.

### Client Test Etme

```bash
python mcp_music_client.py
```

## API Endpoints

- `GET /` - Server durumu
- `POST /upload_audio` - Ses dosyası yükleme
- `POST /tool_call` - MCP tool çağrısı
- `GET /spotify/auth` - Spotify yetkilendirme
- `GET /callback` - Spotify callback

## Desteklenen Ses Formatları

- MP3
- WAV
- M4A
- FLAC

## Güvenlik

⚠️ **ÖNEMLİ**: 
- `.env` dosyası `.gitignore`'da bulunur ve GitHub'a yüklenmez
- API anahtarlarınızı asla kod içerisinde hardcode etmeyin
- Production ortamında environment variables kullanın

## Katkıda Bulunma

1. Fork yapın
2. Feature branch oluşturun (`git checkout -b feature/amazing-feature`)
3. Değişikliklerinizi commit edin (`git commit -m 'Add some amazing feature'`)
4. Branch'inizi push edin (`git push origin feature/amazing-feature`)
5. Pull Request açın

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır.

## Sorun Giderme

### Yaygın Hatalar

1. **"config.json bulunamadı"** - Normal, artık `.env` dosyası kullanılıyor
2. **"python-dotenv yüklenemedi"** - `pip install python-dotenv` çalıştırın
3. **API anahtarı hatası** - `.env` dosyasındaki anahtarları kontrol edin

### Debug Modu

Debug modunu açmak için `.env` dosyasında:

```env
DEBUG=true
```

## Test Sonuçları

Test sonuçları `mcp_music_test_report.json` dosyasında saklanır.

## İletişim

Sorularınız için issue açabilirsiniz.
