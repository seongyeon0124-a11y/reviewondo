import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

BATCH_PROMPT = """당신은 한국 쇼핑몰 사장님을 돕는 리뷰 분석 전문가입니다.
아래 리뷰 목록을 읽고 각 리뷰를 분류하세요.

분류 기준:
- red: 악성 의심 (허위 사실, 욕설, 협박, 경쟁사 공작 의심)
- yellow: 감정적 불만 (실제 문제보다 감정이 과장됨)
- green: 진짜 불만 (제품/서비스의 실제 문제를 이성적으로 지적)
- blue: 긍정 (만족, 칭찬, 재구매 의사)

핵심(summary) 작성 규칙:
- 감정 표현 제거, 소비자가 실제로 원하는 것만 한 줄로
- 예: "배송 너무 늦어요 최악이에요" → "배송 속도 개선 요청"
- 예: "포장 불량으로 스크래치 있었어요 교환 원합니다" → "불량 포장으로 인한 교환 요청"
- 예: "정말 만족해요 재구매 의사 있습니다" → "제품 만족, 재구매 의사"
- 악성 의심은 → "대응 불필요"

리뷰 목록:
{reviews}

정확히 아래 JSON 배열 형식으로만 응답하세요. 다른 텍스트 없이:
[{{"idx":0,"grade":"blue","label":"긍정","summary":"소비자 핵심 요점 한 줄"}}, ...]"""


def classify_reviews(reviews):
    """리뷰 목록 전체를 한 번의 ollama 호출로 분류"""
    results = []
    counts = {"red": 0, "yellow": 0, "green": 0, "blue": 0}

    if not reviews:
        return results, counts

    # 텍스트 목록 구성
    review_texts = "\n".join(
        f"{i}. {r.get('content', '').strip()[:200]}"
        for i, r in enumerate(reviews)
    )

    grades = _batch_classify(review_texts, len(reviews))

    for i, review in enumerate(reviews):
        grade_info = grades.get(i, _keyword_fallback(review.get("content", "")))
        counts[grade_info["grade"]] += 1
        results.append({**review, "classification": grade_info})

    return results, counts


def _batch_classify(review_texts, count):
    """ollama 배치 호출 → {idx: grade_info} 반환"""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": BATCH_PROMPT.format(reviews=review_texts),
                "stream": False
            },
            timeout=60
        )
        raw = resp.json().get("response", "").strip()

        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(raw[start:end])
            result = {}
            colors = {"red": "#FF4444", "yellow": "#FFA500", "green": "#44AA44", "blue": "#4488FF"}
            for item in items:
                raw_grade = str(item.get("grade", "green")).split("|")[0].strip().lower()
                grade = raw_grade if raw_grade in colors else "green"
                result[item["idx"]] = {
                    "grade": grade,
                    "label": item.get("label", grade),
                    "summary": item.get("summary", ""),
                    "color": colors[grade]
                }
            return result
    except Exception:
        pass
    return {}


def _keyword_fallback(text):
    t = text.lower()
    colors = {"red": "#FF4444", "yellow": "#FFA500", "green": "#44AA44", "blue": "#4488FF"}
    if any(k in t for k in ["사기", "쓰레기", "최악", "고소", "신고", "ㅅㅂ", "ㅂㅅ"]):
        grade = "red"
    elif any(k in t for k in ["별로", "실망", "느림", "불량", "교환", "반품", "불친절", "짜증"]):
        grade = "yellow"
    elif any(k in t for k in ["좋아", "최고", "완벽", "만족", "감사", "추천", "재구매", "맛있", "빠름"]):
        grade = "blue"
    else:
        grade = "green"
    labels = {"red": "악성 의심", "yellow": "감정적 불만", "green": "진짜 불만", "blue": "긍정"}
    summaries = {"red": "대응 불필요", "yellow": "감정적 표현 포함된 불만", "green": "제품/서비스 개선 요청", "blue": "긍정 반응"}
    return {"grade": grade, "label": labels[grade], "summary": summaries[grade], "color": colors[grade]}
