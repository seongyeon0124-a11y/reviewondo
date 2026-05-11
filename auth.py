import os
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CAFE24_CLIENT_ID")
CLIENT_SECRET = os.getenv("CAFE24_CLIENT_SECRET")
REDIRECT_URI = os.getenv("CAFE24_REDIRECT_URI")


def get_auth_url(mall_id):
    """사장님이 권한 승인하는 카페24 인증 페이지 URL 생성"""
    scope = "mall.read_community"  # 상품후기(리뷰) 읽기 권한
    return (
        f"https://{mall_id}.cafe24api.com/api/v2/oauth/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scope}"
    )


def get_access_token(mall_id, code):
    """인증 코드로 Access Token 발급"""
    url = f"https://{mall_id}.cafe24api.com/api/v2/oauth/token"
    response = requests.post(
        url,
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    return response.json()


def get_review_board_no(mall_id, access_token):
    """상품 사용후기 게시판 번호 동적으로 찾기 (board_type=5)"""
    url = f"https://{mall_id}.cafe24api.com/api/v2/admin/boards"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers, params={"limit": 100})
    boards = resp.json().get("boards", [])
    for b in boards:
        # board_type=5: 상품 사용후기, board_name에 '후기' 또는 '리뷰' 포함 우선
        if b.get("board_type") == 5 and ("후기" in b.get("board_name", "") or "리뷰" in b.get("board_name", "")):
            return b["board_no"]
    # 이름 무관하게 type=5인 첫 번째
    for b in boards:
        if b.get("board_type") == 5:
            return b["board_no"]
    return None


def get_reviews(mall_id, access_token, limit=20):
    """카페24 쇼핑몰 리뷰 목록 가져오기"""
    board_no = get_review_board_no(mall_id, access_token)
    if board_no is None:
        return {"articles": [], "error": "상품 사용후기 게시판을 찾을 수 없습니다"}

    url = f"https://{mall_id}.cafe24api.com/api/v2/admin/boards/{board_no}/articles"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.get(url, headers=headers, params={"limit": limit})
    return response.json()
