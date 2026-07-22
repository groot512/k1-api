"""
K1 Recipe Extractor — Flask 서버
유튜브 링크 → 레시피 자동 추출 + Supabase DB 저장
"""

import json
import os
import sys
import urllib.request
import urllib.error
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

# Supabase 설정
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


# ─── Supabase 헬퍼 함수 ───────────────────────────────────

def _supabase_request(method, endpoint, data=None, params=None):
    """Supabase REST API 호출 헬퍼 (urllib 사용, 외부 라이브러리 불필요)"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        print(f"[Supabase] HTTP {e.code}: {error_body[:200]}")
        return None
    except Exception as e:
        print(f"[Supabase] 오류: {e}")
        return None


def save_recipe_to_db(video_id, video_url, video_info, recipe, transcript_length):
    """추출된 레시피를 Supabase에 저장합니다. 이미 있으면 업데이트."""
    row = {
        "video_id": video_id,
        "video_url": video_url,
        "video_title": video_info.get("title", ""),
        "video_channel": video_info.get("channel", ""),
        "video_thumbnail": video_info.get("thumbnail", ""),
        "recipe_title": recipe.get("title", "제목 없음"),
        "recipe_description": recipe.get("description", ""),
        "servings": recipe.get("servings", ""),
        "cook_time": recipe.get("cookTime", ""),
        "difficulty": recipe.get("difficulty", "medium"),
        "ingredients": recipe.get("ingredients", []),
        "steps": recipe.get("steps", []),
        "tips": recipe.get("tips", []),
        "transcript_length": transcript_length,
    }

    # UPSERT: video_id가 같으면 업데이트, 없으면 새로 삽입
    headers_extra = {"Prefer": "return=representation,resolution=merge-duplicates"}
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[Supabase] URL/KEY 미설정 — 저장 건너뜀")
        return None

    url = f"{SUPABASE_URL}/rest/v1/recipes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    body = json.dumps(row).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"[Supabase] 저장 성공: {recipe.get('title', '?')}")
            return result
    except Exception as e:
        print(f"[Supabase] 저장 실패: {e}")
        return None


# ─── API 라우트 ──────────────────────────────────────────

@app.route("/")
def index():
    """유튜브 레시피 추출 메인 페이지"""
    return render_template("youtube.html")


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """유튜브 URL을 받아 레시피를 추출하고 DB에 저장하는 API"""
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

        # Supabase에 저장 (실패해도 추출 결과는 반환)
        saved = save_recipe_to_db(
            video_id=result.get("videoId", ""),
            video_url=youtube_url,
            video_info=result.get("videoInfo", {}),
            recipe=result.get("recipe", {}),
            transcript_length=result.get("transcriptLength", 0),
        )
        result["saved"] = saved is not None

        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"처리 중 오류가 발생했습니다: {str(e)}"}), 500


@app.route("/api/recipes", methods=["GET"])
def api_recipes():
    """저장된 레시피 목록 조회"""
    # 쿼리 파라미터
    limit = request.args.get("limit", "20")
    offset = request.args.get("offset", "0")

    params = {
        "select": "id,video_id,video_thumbnail,recipe_title,recipe_description,cook_time,difficulty,servings,created_at",
        "order": "created_at.desc",
        "limit": limit,
        "offset": offset,
    }
    result = _supabase_request("GET", "recipes", params=params)
    if result is None:
        return jsonify({"error": "DB 연결 실패 또는 미설정"}), 500
    return jsonify(result)


@app.route("/api/recipes/<video_id>", methods=["GET"])
def api_recipe_detail(video_id):
    """특정 레시피 상세 조회 (video_id로)"""
    params = {
        "select": "*",
        "video_id": f"eq.{video_id}",
        "limit": "1",
    }
    result = _supabase_request("GET", "recipes", params=params)
    if result is None:
        return jsonify({"error": "DB 연결 실패"}), 500
    if not result:
        return jsonify({"error": "레시피를 찾을 수 없습니다."}), 404
    return jsonify(result[0])


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
    sb = "✅" if SUPABASE_URL else "❌ 미설정"
    print(f"🍳 K1 Recipe Extractor 서버 시작!")
    print(f"   → http://localhost:{port}")
    print(f"   → 프록시: {'✅ ' + proxy[:30] + '...' if proxy else '❌ 없음'}")
    print(f"   → Supabase: {sb}")
    print(f"   → Ctrl+C 로 종료\n")
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1")
    app.run(host="0.0.0.0", debug=debug, port=port)
