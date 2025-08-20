#!/usr/bin/env python3
"""
Music Recognition + Spotify MCP Client
Ses dosyalarını tanıyıp Spotify'a ekleyen MCP client
"""

import httpx
import json
import time
import asyncio
import os
from datetime import datetime
from typing import Dict, Any, List
import sys
from pathlib import Path

class MusicMCPClient:
    def __init__(self, base_url: str = "http://localhost:8002"):
        self.base_url = base_url
        self.session = httpx.AsyncClient(timeout=60.0)  # Müzik tanıma uzun sürebilir
        self.test_results = []
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_response_time": 0.0,
            "total_data_transferred": 0,
            "audio_files_processed": 0,
            "songs_recognized": 0,
            "spotify_actions": 0,
            "start_time": datetime.now()
        }

    async def close(self):
        """Client'ı kapat"""
        await self.session.aclose()

    async def make_request(self, method: str, endpoint: str, data: Dict = None, files: Dict = None) -> Dict[str, Any]:
        """HTTP request gönder ve metrikleri topla"""
        start_time = time.time()
        
        try:
            if method.upper() == "GET":
                response = await self.session.get(f"{self.base_url}{endpoint}")
            elif method.upper() == "POST":
                if files:
                    response = await self.session.post(f"{self.base_url}{endpoint}", files=files)
                else:
                    response = await self.session.post(f"{self.base_url}{endpoint}", json=data)
            else:
                raise ValueError(f"Desteklenmeyen HTTP method: {method}")
            
            end_time = time.time()
            response_time = end_time - start_time
            
            # Metrikleri güncelle
            self.metrics["total_requests"] += 1
            self.metrics["total_response_time"] += response_time
            
            if response.status_code == 200:
                self.metrics["successful_requests"] += 1
            else:
                self.metrics["failed_requests"] += 1
            
            # Veri boyutu hesapla
            request_size = len(json.dumps(data).encode('utf-8')) if data else 0
            response_size = len(response.content)
            self.metrics["total_data_transferred"] += request_size + response_size
            
            result = {
                "status_code": response.status_code,
                "response_time": response_time,
                "request_size": request_size,
                "response_size": response_size,
                "success": response.status_code == 200
            }
            
            if response.status_code == 200:
                result["data"] = response.json()
            else:
                result["error"] = response.text
                
            return result
            
        except Exception as e:
            end_time = time.time()
            self.metrics["total_requests"] += 1
            self.metrics["failed_requests"] += 1
            self.metrics["total_response_time"] += (end_time - start_time)
            
            return {
                "status_code": 0,
                "response_time": end_time - start_time,
                "success": False,
                "error": str(e)
            }

    async def test_server_health(self):
        """Server sağlık kontrolü"""
        print(">> Music MCP Server sağlık kontrolü...")
        result = await self.make_request("GET", "/")
        
        test_result = {
            "test_name": "Music Server Health Check",
            "success": result["success"],
            "response_time": result["response_time"],
            "details": result.get("data", result.get("error"))
        }
        
        self.test_results.append(test_result)
        
        if result["success"]:
            data = result["data"]
            print(f"   OK Server çalışıyor: {data['status']}")
            print(f"      - Müzik Tanıma: {data['services']['music_recognition']}")
            print(f"      - Spotify: {data['services']['spotify']}")
            print(f"      - İstatistikler: {data['stats']['recognized_songs']} şarkı tanındı")
        else:
            print(f"   ERR Server erişilemez: {result.get('error')}")
        
        return result

    async def list_tools(self):
        """Mevcut tool'ları listele"""
        print(">> Music MCP tool'larını listeleniyor...")
        result = await self.make_request("GET", "/tools")
        
        test_result = {
            "test_name": "List Music Tools",
            "success": result["success"],
            "response_time": result["response_time"],
            "details": result.get("data", result.get("error"))
        }
        
        self.test_results.append(test_result)
        
        if result["success"]:
            tools = result["data"]["tools"]
            print(f"   OK {len(tools)} music tool bulundu:")
            for tool in tools:
                print(f"      - {tool['name']}: {tool['description']}")
        else:
            print(f"   ERR Tool listesi alınamadı: {result.get('error')}")
            
        return result

    async def upload_audio_file(self, file_path: str):
        """Ses dosyası yükle"""
        print(f">> Ses dosyası yükleniyor: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"   ERR Dosya bulunamadı: {file_path}")
            return None
        
        try:
            with open(file_path, "rb") as f:
                files = {
                    "file": (os.path.basename(file_path), f, "audio/mpeg")
                }
                result = await self.make_request("POST", "/upload", files=files)
            
            test_result = {
                "test_name": f"Upload Audio: {os.path.basename(file_path)}",
                "success": result["success"],
                "response_time": result["response_time"],
                "file_path": file_path,
                "details": result.get("data", result.get("error"))
            }
            
            self.test_results.append(test_result)
            
            if result["success"]:
                data = result["data"]
                self.metrics["audio_files_processed"] += 1
                print(f"   OK Dosya yüklendi: {data['filename']}")
                print(f"      - Dosya ID: {data['file_id']}")
                print(f"      - Boyut: {data['size']:,} bytes")
                print(f"      - Format: {data['format']}")
                return data["file_id"]
            else:
                print(f"   ERR Dosya yüklenemedi: {result.get('error')}")
                return None
                
        except Exception as e:
            print(f"   ERR Dosya yükleme hatası: {str(e)}")
            return None

    async def call_tool(self, tool_name: str, parameters: Dict[str, Any] = {}):
        """Music MCP tool'u çağır"""
        print(f">> Tool çağrılıyor: {tool_name}")
        
        request_data = {
            "tool_name": tool_name,
            "parameters": parameters
        }
        
        result = await self.make_request("POST", "/tools/call", request_data)
        
        test_result = {
            "test_name": f"Call Tool: {tool_name}",
            "success": result["success"],
            "response_time": result["response_time"],
            "parameters": parameters,
            "details": result.get("data", result.get("error"))
        }
        
        self.test_results.append(test_result)
        
        if result["success"]:
            response_data = result["data"]["result"]
            print(f"   OK Tool başarılı: {tool_name}")
            
            # Tool'a özgü sonuç gösterimi
            if tool_name == "recognize_music":
                recognition = response_data.get("recognition", {})
                status_code = recognition.get("status", {}).get("code", -1)
                status_msg = recognition.get("status", {}).get("msg", "Bilinmiyor")
                
                print(f"      - Tanıma durumu: {status_msg}")
                
                if status_code == 0:
                    music_list = recognition.get("metadata", {}).get("music", [])
                    if music_list:
                        music_data = music_list[0]
                        self.metrics["songs_recognized"] += 1
                        print(f"      - Şarkı: {music_data.get('title', 'Bilinmiyor')}")
                        
                        artists = music_data.get('artists', [])
                        if artists:
                            artist_names = [artist.get('name', '') for artist in artists]
                            print(f"      - Sanatçı: {', '.join(artist_names)}")
                        
                        album = music_data.get('album', {})
                        if album:
                            print(f"      - Albüm: {album.get('name', 'Bilinmiyor')}")
                            
                        if music_data.get("score"):
                            print(f"      - Güven Skoru: {music_data.get('score')}%")
                            
                        # Spotify ID varsa göster
                        external_ids = music_data.get("external_ids", {})
                        if external_ids.get("spotify"):
                            print(f"      - Spotify ID: {external_ids.get('spotify')}")
                    else:
                        print("      - Şarkı verisi bulunamadı")
                else:
                    print(f"      - Şarkı tanınamadı: {status_msg}")
                    
            elif tool_name == "search_spotify":
                results = response_data.get("results", {}).get("tracks", {}).get("items", [])
                print(f"      - {len(results)} Spotify sonucu bulundu")
                if results:
                    track = results[0]
                    print(f"      - En iyi eşleşme: {track['name']} - {track['artists'][0]['name']}")
                    print(f"      - Spotify ID: {track['id']}")
                    
            elif tool_name == "add_to_liked_songs":
                self.metrics["spotify_actions"] += 1
                print(f"      - Şarkı beğenilen şarkılara eklendi: {response_data.get('track_id')}")
                
            elif tool_name == "get_user_profile":
                profile = response_data.get("profile", {})
                print(f"      - Kullanıcı: {profile.get('display_name', 'Bilinmiyor')}")
                print(f"      - Ülke: {profile.get('country', 'Bilinmiyor')}")
                print(f"      - Abonelik: {profile.get('product', 'Bilinmiyor')}")
                
            elif tool_name == "get_playlists":
                playlists = response_data.get("playlists", {}).get("items", [])
                print(f"      - {len(playlists)} playlist bulundu")
                for playlist in playlists[:3]:  # İlk 3'ünü göster
                    print(f"        * {playlist['name']}: {playlist['tracks']['total']} şarkı")
                    
        else:
            error_detail = result.get('error', {})
            if isinstance(error_detail, dict):
                error_msg = error_detail.get('detail', str(error_detail))
            else:
                error_msg = str(error_detail)
                
            print(f"   ERR Tool hatası: {error_msg}")
            
            # Spotify OAuth gerekli mi kontrol et
            if tool_name in ["add_to_liked_songs", "get_user_profile", "get_playlists"]:
                if "Tool çalıştırma hatası" in error_msg:
                    print(f"      !! Spotify OAuth gerekli. Önce şu URL'e gidin:")
                    print(f"         http://127.0.0.1:8002/spotify/login")
            
        return result

    async def get_context(self):
        """Server context bilgisi"""
        print(">> Music MCP context bilgisi alınıyor...")
        result = await self.make_request("GET", "/context")
        
        test_result = {
            "test_name": "Get Music Context",
            "success": result["success"],
            "response_time": result["response_time"],
            "details": result.get("data", result.get("error"))
        }
        
        self.test_results.append(test_result)
        
        if result["success"]:
            context = result["data"]
            print(f"   OK Context alındı: {context['server']}")
            print(f"      - Yetenekler: {', '.join(context['capabilities'])}")
            print(f"      - Desteklenen Formatlar: {', '.join(context['supported_formats'])}")
            print(f"      - İş Akışı:")
            for step in context['workflow']:
                print(f"        {step}")
        else:
            print(f"   ERR Context alınamadı: {result.get('error')}")
            
        return result

    async def demo_workflow(self, audio_file_path: str = None):
        """Tam müzik tanıma + Spotify ekleme workflow'u"""
        print("=" * 60)
        print(">> MUSIC RECOGNITION + SPOTIFY WORKFLOW DEMO")
        print("=" * 60)
        
        # 1. Ses dosyası yükle
        if audio_file_path and os.path.exists(audio_file_path):
            file_id = await self.upload_audio_file(audio_file_path)
            if not file_id:
                print("!! Ses dosyası yüklenemedi, demo ses dosyası kullanılacak")
                file_id = "demo_file_id"
        else:
            print(">> Demo ses dosyası kullanılıyor (gerçek dosya yolu verilmedi)")
            file_id = "demo_file_id"
        
        print()
        
        # 2. Müziği tanı
        recognition_result = await self.call_tool("recognize_music", {"file_id": file_id})
        
        if not recognition_result["success"]:
            print("!! Müzik tanıma başarısız, demo devam ediyor")
        
        print()
        
        # 3. Spotify'da ara
        search_result = await self.call_tool("search_spotify", {
            "query": "Shape of You Ed Sheeran",
            "type": "track"
        })
        
        spotify_track_id = None
        if search_result["success"]:
            results = search_result["data"]["result"].get("results", {}).get("tracks", {}).get("items", [])
            if results:
                spotify_track_id = results[0]["id"]
        
        print()
        
        # 4. Beğenilenlere ekle
        if spotify_track_id:
            await self.call_tool("add_to_liked_songs", {"track_id": spotify_track_id})
        else:
            print(">> Spotify track ID bulunamadı, demo ID kullanılıyor")
            await self.call_tool("add_to_liked_songs", {"track_id": "demo_track_id"})
        
        print()
        
        # 5. Kullanıcı profili ve playlist'leri göster
        await self.call_tool("get_user_profile")
        print()
        await self.call_tool("get_playlists")
        
        print("\n" + "=" * 60)
        print(">> WORKFLOW TAMAMLANDI!")
        print("=" * 60)

    async def run_comprehensive_music_test(self, audio_file_path: str = None):
        """Kapsamlı müzik MCP testi"""
        print("=" * 60)
        print(">> MUSIC RECOGNITION + SPOTIFY MCP - KAPSAMLI TEST")
        print("=" * 60)
        
        # Test senaryoları
        scenarios = [
            {"name": "Server Health", "func": self.test_server_health},
            {"name": "List Tools", "func": self.list_tools},
            {"name": "Get Context", "func": self.get_context},
            {"name": "Demo Workflow", "func": lambda: self.demo_workflow(audio_file_path)},
        ]
        
        print(f"\n>> {len(scenarios)} test senaryosu çalıştırılacak...\n")
        
        for i, scenario in enumerate(scenarios, 1):
            print(f"[{i:2d}/{len(scenarios)}] {scenario['name']}")
            try:
                await scenario["func"]()
            except Exception as e:
                print(f"   ERR Test hatası: {str(e)}")
                self.test_results.append({
                    "test_name": scenario["name"],
                    "success": False,
                    "error": str(e)
                })
            
            print()  # Boş satır
            await asyncio.sleep(1.0)  # Server'a nefes aldır

        # Test sonuçları
        await self.generate_music_test_report()

    async def generate_music_test_report(self):
        """Müzik test raporu oluştur"""
        print("=" * 60)
        print(">> MUSIC MCP TEST RAPORU OLUSTURULUYOR")
        print("=" * 60)
        
        # Kalite metrikleri
        total_tests = len(self.test_results)
        successful_tests = sum(1 for test in self.test_results if test["success"])
        failed_tests = total_tests - successful_tests
        
        # Performans metrikleri
        avg_response_time = (
            self.metrics["total_response_time"] / self.metrics["total_requests"]
            if self.metrics["total_requests"] > 0 else 0
        )
        
        test_duration = (datetime.now() - self.metrics["start_time"]).total_seconds()
        
        # Rapor
        report = {
            "test_info": {
                "server_type": "Music Recognition + Spotify MCP Server",
                "services": ["ACRCloud API", "Spotify Web API"],
                "test_date": datetime.now().isoformat(),
                "test_duration_seconds": test_duration,
                "client_version": "1.0.0"
            },
            "quality_metrics": {
                "total_test_scenarios": total_tests,
                "successful_tests": successful_tests,
                "failed_tests": failed_tests,
                "success_rate_percentage": (successful_tests / total_tests * 100) if total_tests > 0 else 0,
                "test_results": self.test_results
            },
            "efficiency_metrics": {
                "total_http_requests": self.metrics["total_requests"],
                "successful_http_requests": self.metrics["successful_requests"],
                "failed_http_requests": self.metrics["failed_requests"],
                "total_data_transferred_bytes": self.metrics["total_data_transferred"],
                "average_response_time_seconds": avg_response_time,
                "requests_per_second": self.metrics["total_requests"] / test_duration if test_duration > 0 else 0
            },
            "music_metrics": {
                "audio_files_processed": self.metrics["audio_files_processed"],
                "songs_recognized": self.metrics["songs_recognized"],
                "spotify_actions": self.metrics["spotify_actions"],
                "recognition_success_rate": (
                    self.metrics["songs_recognized"] / self.metrics["audio_files_processed"] * 100
                    if self.metrics["audio_files_processed"] > 0 else 0
                )
            },
            "service_analysis": {
                "music_recognition": "ACRCloud API (Demo Mode)",
                "spotify_integration": "Spotify Web API (Demo Mode)",
                "supported_audio_formats": ["MP3", "WAV", "M4A", "FLAC"],
                "max_file_size_mb": 10,
                "workflow_steps": [
                    "Audio file upload",
                    "Music recognition",
                    "Spotify search",
                    "Add to liked songs"
                ]
            }
        }
        
        # Konsol çıktısı
        print(f"\n>> KALITE METRIKLERI:")
        print(f"   - Toplam Test: {total_tests}")
        print(f"   - Başarılı: {successful_tests}")
        print(f"   - Başarısız: {failed_tests}")
        print(f"   - Başarı Oranı: {report['quality_metrics']['success_rate_percentage']:.1f}%")
        
        print(f"\n>> PERFORMANS METRIKLERI:")
        print(f"   - Toplam HTTP İsteği: {self.metrics['total_requests']}")
        print(f"   - Veri Transferi: {self.metrics['total_data_transferred']:,} bytes")
        print(f"   - Ortalama Yanıt Süresi: {avg_response_time:.3f} saniye")
        print(f"   - İstek/Saniye: {report['efficiency_metrics']['requests_per_second']:.2f}")
        
        print(f"\n>> MÜZIK METRIKLERI:")
        print(f"   - İşlenen Ses Dosyası: {self.metrics['audio_files_processed']}")
        print(f"   - Tanınan Şarkı: {self.metrics['songs_recognized']}")
        print(f"   - Spotify İşlemi: {self.metrics['spotify_actions']}")
        print(f"   - Tanıma Başarı Oranı: {report['music_metrics']['recognition_success_rate']:.1f}%")
        
        print(f"\n>> SERVİS ANALİZİ:")
        print(f"   - Müzik Tanıma: {report['service_analysis']['music_recognition']}")
        print(f"   - Spotify Entegrasyonu: {report['service_analysis']['spotify_integration']}")
        print(f"   - Desteklenen Formatlar: {', '.join(report['service_analysis']['supported_audio_formats'])}")
        print(f"   - Maksimum Dosya Boyutu: {report['service_analysis']['max_file_size_mb']} MB")
        
        # JSON raporu kaydet
        try:
            with open("mcp_music_test_report.json", "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\n>> Detaylı rapor kaydedildi: mcp_music_test_report.json")
        except Exception as e:
            print(f"\n!! Rapor kaydetme hatası: {str(e)}")
        
        print("=" * 60)
        print(">> MUSIC MCP TEST TAMAMLANDI!")
        print("=" * 60)

async def main():
    """Ana test fonksiyonu"""
    client = MusicMCPClient()
    
    # Komut satırı argümanı olarak ses dosyası yolu
    audio_file = None
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        if not os.path.exists(audio_file):
            print(f"!! Ses dosyası bulunamadı: {audio_file}")
            audio_file = None
    
    try:
        await client.run_comprehensive_music_test(audio_file)
    except KeyboardInterrupt:
        print("\n!! Test kullanıcı tarafından durduruldu")
    except Exception as e:
        print(f"\n!! Test hatası: {str(e)}")
    finally:
        await client.close()

if __name__ == "__main__":
    print(">> Music Recognition + Spotify MCP Client başlatılıyor...")
    print(">> Ses dosyalarını tanıyıp Spotify'a ekleyecek")
    print(">> Kullanım: python mcp_music_client.py [ses_dosyasi.mp3]")
    print()
    
    asyncio.run(main())