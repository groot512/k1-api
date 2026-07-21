"""
유튜브 영상 → 레시피 자동 추출 핵심 로직
자막 + GPT로 재료/조리단계/타임스탬프를 구조화합니다.
"""

import json
import os
import re
import subprocess
import sys
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi

# 프록시 설정 (Render 등 클라우드에서 유튜브 IP 차단 우회)
PROXY_URL = os.getenv("PROXY_URL", "")


def extract_video_id(url: str) -> str:
    """유튜브 URL에서 영상 ID를 추출합니다."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # URL 자체가 11자리 ID일 수도 있음
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
    raise ValueError(f"유효한 유튜브 URL이 아닙니다: {url}")


def get_video_info(video_id: str) -> dict:
    """yt-dlp로 영상 메타데이터를 가져옵니다."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "--dump-json", "--no-download",
                f"https://www.youtube.com/watch?v={video_id}"
            ],
            capture_output=True, text=True, timeout=30, encoding="utf-8"
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp 오류: {result.stderr[:200]}")
        data = json.loads(result.stdout)
        return {
            "title": data.get("title", ""),
            "channel": data.get("channel", data.get("uploader", "")),
            "description": data.get("description", ""),
            "thumbnail": data.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"),
            "duration": data.get("duration", 0),
            "view_count": data.get("view_count", 0),
        }
    except Exception:
        # yt-dlp 실패(미설치, JS 런타임 없음 등) → 기본 정보만 반환
        return {
            "title": "",
            "channel": "",
            "description": "",
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            "duration": 0,
            "view_count": 0,
        }


def _build_ytt():
    """프록시 설정이 있으면 적용한 YouTubeTranscriptApi 인스턴스를 만듭니다."""
    if PROXY_URL:
        try:
            from youtube_transcript_api.proxies import GenericProxyConfig
            proxy_config = GenericProxyConfig(
                http_url=PROXY_URL,
                https_url=PROXY_URL,
            )
            return YouTubeTranscriptApi(proxy_config=proxy_config)
        except ImportError:
            # 구버전 호환: 환경변수로 프록시 설정
            os.environ["HTTP_PROXY"] = PROXY_URL
            os.environ["HTTPS_PROXY"] = PROXY_URL
            return YouTubeTranscriptApi()
    return YouTubeTranscriptApi()


def get_transcript(video_id: str) -> list[dict]:
    """유튜브 자막을 가져옵니다 (한국어 우선, 없으면 자동생성 자막).
    youtube-transcript-api v1.x 호환. 프록시 지원."""
    ytt = _build_ytt()
    
    try:
        # 한국어 → 영어 → 일본어 → 중국어 순으로 시도
        transcript = ytt.fetch(video_id, languages=['ko', 'en', 'ja', 'zh'])
        # v1.x는 FetchedTranscript 객체를 반환, 이터러블
        result = []
        for snippet in transcript:
            result.append({
                "start": snippet.start,
                "duration": snippet.duration,
                "text": snippet.text,
            })
        return result
    except Exception as e:
        raise RuntimeError(f"자막을 가져올 수 없습니다: {str(e)}")


def format_timestamp(seconds: float) -> str:
    """초를 MM:SS 또는 H:MM:SS 형식으로 변환합니다."""
    seconds = int(seconds)
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}:{m:02d}:{s:02d}"
    else:
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"


def transcript_to_text_with_timestamps(transcript: list[dict]) -> str:
    """자막 리스트를 타임스탬프 포함 텍스트로 변환합니다."""
    lines = []
    for entry in transcript:
        start = entry.get("start", entry.get("offset", 0))
        # youtube_transcript_api v1.x는 .start, 구버전은 다를 수 있음
        if hasattr(entry, "start"):
            start = entry.start
        elif isinstance(entry, dict):
            start = entry.get("start", 0)
        
        text = entry.get("text", str(entry))
        if hasattr(entry, "text"):
            text = entry.text
            
        ts = format_timestamp(start)
        lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def extract_recipe_with_gpt(client: OpenAI, video_info: dict, transcript_text: str, model: str = "gpt-4o-mini") -> dict:
    """GPT를 사용해 자막에서 레시피를 구조화합니다."""
    
    system_prompt = """당신은 요리 레시피 전문 분석가입니다. 유튜브 요리 영상의 자막을 받아서 구조화된 레시피로 정리합니다.

반드시 아래 JSON 형식으로 응답하세요. 다른 텍스트 없이 JSON만 반환하세요.

{
  "title": "요리 이름 (예: 꽁치 김치찌개)",
  "description": "이 요리에 대한 1-2줄 설명",
  "servings": "인분 (예: 2인분)",
  "cookTime": "조리 시간 (예: 30분)",
  "difficulty": "easy 또는 medium 또는 hard",
  "ingredients": [
    {"name": "재료명", "amount": "분량 (예: 200g, 1큰술, 2개)"},
    ...
  ],
  "steps": [
    {
      "step": 1,
      "timestamp": "MM:SS",
      "title": "단계 제목 (간결하게, 예: 재료 손질하기)",
      "description": "구체적인 조리 방법 설명"
    },
    ...
  ],
  "tips": ["요리 팁이 있으면 여기에 (없으면 빈 배열)"]
}

규칙:
1. 재료는 자막에서 언급된 모든 재료를 빠짐없이, 분량까지 정확히 적으세요.
2. 조리 단계는 논리적 흐름에 따라 5-12단계로 나누세요.
3. 각 단계의 timestamp는 해당 내용이 자막에서 시작되는 시점입니다. [MM:SS] 형식의 타임스탬프를 참고하세요.
4. 자막에서 언급하는 꿀팁, 주의사항은 tips에 넣으세요.
5. 분량이 명확하지 않으면 "적당량" 또는 "약간"으로 표기하세요.
"""

    user_prompt = f"""아래는 유튜브 요리 영상의 정보입니다.

영상 제목: {video_info.get('title', '알 수 없음')}
채널: {video_info.get('channel', '알 수 없음')}

영상 설명:
{video_info.get('description', '')[:500]}

자막 (타임스탬프 포함):
{transcript_text}

위 자막을 분석해서 레시피를 JSON으로 정리해주세요."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    
    result_text = response.choices[0].message.content
    recipe = json.loads(result_text)
    return recipe


def extract_recipe(youtube_url: str, api_key: str, model: str = "gpt-4o-mini") -> dict:
    """
    메인 함수: 유튜브 URL → 구조화된 레시피 데이터
    
    Returns:
        {
            "videoId": "...",
            "videoInfo": { title, channel, thumbnail, ... },
            "recipe": { title, ingredients, steps, ... }
        }
    """
    # 1. 영상 ID 추출
    video_id = extract_video_id(youtube_url)
    
    # 2. 영상 메타데이터
    video_info = get_video_info(video_id)
    
    # 3. 자막 추출
    transcript = get_transcript(video_id)
    transcript_text = transcript_to_text_with_timestamps(transcript)
    
    # 4. GPT로 레시피 구조화
    client = OpenAI(api_key=api_key)
    recipe = extract_recipe_with_gpt(client, video_info, transcript_text, model)
    
    return {
        "videoId": video_id,
        "videoInfo": video_info,
        "recipe": recipe,
        "transcriptLength": len(transcript),
    }


# CLI에서 직접 실행할 때
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ .env 파일에 OPENAI_API_KEY를 설정해주세요.")
        sys.exit(1)
    
    if len(sys.argv) < 2:
        print("사용법: python extractor.py <유튜브URL>")
        print("예시:   python extractor.py https://youtu.be/abc123def45")
        sys.exit(1)
    
    url = sys.argv[1]
    print(f"🔍 영상 분석 중: {url}")
    
    try:
        result = extract_recipe(url, api_key)
        print(f"\n✅ 추출 완료!")
        print(f"📺 {result['videoInfo']['title']} ({result['videoInfo']['channel']})")
        print(f"📝 자막 {result['transcriptLength']}줄 분석")
        print(f"\n{'='*60}")
        print(json.dumps(result["recipe"], ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"❌ 오류: {e}")
        sys.exit(1)
