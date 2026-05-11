import os
from flask import Flask, request, redirect, session, jsonify, render_template_string
from dotenv import load_dotenv
from auth import get_auth_url, get_access_token, get_reviews
from classifier import classify_reviews

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")


MAIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>리뷰온도</title>
    <style>
        body { font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        input { width: 100%; padding: 10px; margin: 10px 0; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #4488FF; color: white;
                 border: none; font-size: 16px; cursor: pointer; border-radius: 6px; }
        button:hover { background: #2266DD; }
    </style>
</head>
<body>
    <h2>리뷰온도</h2>
    <p>카페24 쇼핑몰 아이디를 입력하세요</p>
    <form action="/login" method="get">
        <input name="mall_id" placeholder="예: myshop (myshop.cafe24.com에서 myshop 부분)" required>
        <button type="submit">연결하기</button>
    </form>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(MAIN_HTML)


@app.route("/login")
def login():
    mall_id = request.args.get("mall_id", "").strip()
    if not mall_id:
        return redirect("/")
    session["mall_id"] = mall_id
    return redirect(get_auth_url(mall_id))


@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"오류: {error} — {request.args.get('error_description', '')}", 400

    if not code:
        return "code 없음", 400

    mall_id = session.get("mall_id")
    if not mall_id:
        return "세션 만료. 다시 시도해주세요.", 400

    token_data = get_access_token(mall_id, code)
    if "access_token" not in token_data:
        return f"토큰 발급 실패: {token_data}", 400

    session["access_token"] = token_data["access_token"]
    return redirect("/reviews")


@app.route("/reviews")
def reviews():
    mall_id = session.get("mall_id")
    access_token = session.get("access_token")

    if not mall_id or not access_token:
        return redirect("/")

    data = get_reviews(mall_id, access_token)

    if "error" in data and "articles" not in data:
        return jsonify({"오류": data.get("error", "알 수 없는 오류")}), 400

    if data.get("error"):
        return jsonify({"오류": data["error"]}), 400

    # 401: 토큰 만료
    if data.get("code") == 401 or data.get("error", {}).get("code") == 401 if isinstance(data.get("error"), dict) else False:
        session.clear()
        return redirect("/")

    raw_reviews = data.get("articles", [])
    classified, counts = classify_reviews(raw_reviews)

    return jsonify({
        "요약": {
            "파랑(긍정)": counts["blue"],
            "초록(진짜불만)": counts["green"],
            "노랑(감정적불만)": counts["yellow"],
            "빨강(악성의심)": counts["red"],
        },
        "리뷰수": len(raw_reviews),
        "리뷰목록": classified
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
