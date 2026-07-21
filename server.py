"""
K1 Recipe Extractor — Flask 서버
유튜브 링크 → 레시피 자동 추출 웹 서비스
"""

import os
import sys
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드 (override=True로 기존 환경변수도 덮어쓰기)
load_dotenv(override=True)

# 상위 폴더(k1_platform)도 정적 파일로 서빙할 수 있게 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
K1_DIR = os.path.dirname(BASE_DIR)  # k1_platform/

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
CORS(app)  # 외부 사이트(GitHub Pages 등)에서 API 호출 허용

# API 키 확인
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


@app.route("/")
def index():
    """유튜브 레시피 추출 메인 페이지"""
    return render_template("youtube.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """유튜브 URL을 받아 레시피를 추출하는 API"""
    if not OPENAI_API_KEY:
        return jsonify({"error": "서버에 OPENAI_API_KEY가 설정되지 않았습니다."}), 500
    
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"error": "유튜브 URL을 입력해주세요."}), 400
    
    youtube_url = data["url"].strip()
    if not youtube_url:
        return jsonify({"error": "유튜브 URL을 입력해주세요."}), 400
    
    model = data.get("model", "gpt-4o-mini")
    
    try:
        from extractor import extract_recipe
        result = extract_recipe(youtube_url, OPENAI_API_KEY, model)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"처리 중 오류가 발생했습니다: {str(e)}"}), 500


@app.route("/k1/<path:filename>")
def serve_k1(filename):
    """기존 k1_platform 정적 파일 서빙 (선택)"""
    return send_from_directory(K1_DIR, filename)


if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("⚠️  경고: OPENAI_API_KEY가 설정되지 않았습니다.")
        print("   .env 파일을 만들고 OPENAI_API_KEY=sk-... 를 추가하세요.")
        print("   (추출 API는 키 없이는 작동하지 않습니다)\n")
    
    port = int(os.getenv("PORT", 5000))
    proxy = os.getenv("PROXY_URL", "")
    print(f"🍳 K1 Recipe Extractor 서버 시작!")
    print(f"   → http://localhost:{port}")
    print(f"   → 프록시: {'✅ ' + proxy[:30] + '...' if proxy else '❌ 없음 (클라우드에서 유튜브 차단될 수 있음)'}")
    print(f"   → Ctrl+C 로 종료\n")
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1")
    app.run(host="0.0.0.0", debug=debug, port=port)
