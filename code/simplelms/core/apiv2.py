import jwt
import datetime
import os
from typing import Any, List, Optional
from ninja import NinjaAPI, Schema, Query
from ninja.pagination import PaginationBase, paginate
from ninja.security import HttpBearer
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from ninja.errors import HttpError
from .models import User, Course, CourseMember, CourseContent, Comment
from .throttling import SimpleRateThrottle
from .apiv2_schemas import CourseSchema, CourseMemberOut

# ==========================================
# 1. AUTHENTICATION LOGIC (HYBRID & TOLERANT)
# ==========================================

def get_rsa_keys():
    """Mencoba load RSA Keys"""
    priv, pub = None, None
    try:
        priv_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pem')
        pub_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pub')
        if os.path.exists(priv_path):
            with open(priv_path, 'rb') as f: priv = f.read()
        if os.path.exists(pub_path):
            with open(pub_path, 'rb') as f: pub = f.read()
    except:
        pass
    return priv, pub

def create_token_pair(user_id):
    """Membuat token manual (Pengganti Library)"""
    priv_key, _ = get_rsa_keys()
    
    # Pilih Key & Algoritma
    key = priv_key if priv_key else settings.SECRET_KEY
    algo = "RS256" if priv_key else "HS256"

    payload_access = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "type": "access"
    }
    payload_refresh = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
        "type": "refresh"
    }

    access = jwt.encode(payload_access, key, algorithm=algo)
    refresh = jwt.encode(payload_refresh, key, algorithm=algo)
    
    if isinstance(access, bytes): access = access.decode('utf-8')
    if isinstance(refresh, bytes): refresh = refresh.decode('utf-8')
    
    return access, refresh

class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        # 1. Bersihkan prefix "Bearer " (Biar Swagger & Test sama-sama jalan)
        if token.lower().startswith("bearer "):
            token = token.split(" ")[1]

        # 2. Siapkan Kandidat Key (Coba RSA dulu, kalau gagal coba Secret)
        _, pub_key = get_rsa_keys()
        candidates = []
        if pub_key: candidates.append({"key": pub_key, "algo": "RS256"})
        candidates.append({"key": settings.SECRET_KEY, "algo": "HS256"})

        # 3. Coba Decode
        for opt in candidates:
            try:
                payload = jwt.decode(token, opt["key"], algorithms=[opt["algo"]])
                if payload.get("type") == "access":
                    user_id = payload.get("user_id")
                    return User.objects.get(pk=user_id)
            except:
                continue
        return None

# Gunakan Custom Auth ini
apiAuth = CustomJwtAuth()

# ==========================================
# 2. NINJA API SETUP
# ==========================================
api_v2 = NinjaAPI(
    title="SimpleLMS API v2",
    version="2.0.0",
    throttle=SimpleRateThrottle(),
    urls_namespace="api_v2"
)

# ==========================================
# 3. SCHEMAS
# ==========================================
class MobileSignInSchema(Schema):
    username: str
    password: str

class MobileRefreshSchema(Schema):
    refresh: str

class TokenResponseSchema(Schema):
    access: str
    refresh: str

class UserOut(Schema):
    id: int
    username: str
    email: str

class CommentOut(Schema):
    id: int
    comment: str
    user_id: int
    content_id: int

class CommentIn(Schema):
    comment: str
    content_id: int

class SuccessOut(Schema):
    success: bool
    comment_id: Optional[int] = None

class CustomPagination(PaginationBase):
    class Input(Schema):
        skip: int = 0
        limit: int = 5
    class Output(Schema):
        items: List[Any]
        total: int
        per_page: int
    def paginate_queryset(self, queryset, pagination: Input, **params):
        skip, limit = pagination.skip, pagination.limit
        total = queryset.count() if not isinstance(queryset, list) else len(queryset)
        return {"items": queryset[skip : skip + limit], "total": total, "per_page": limit}

# ==========================================
# 4. AUTH ENDPOINTS (INI YANG BIKIN MUNCUL DI DOCS)
# ==========================================

@api_v2.post("/auth/sign-in", response=TokenResponseSchema, auth=None)
def mobile_sign_in(request, data: MobileSignInSchema):
    """Endpoint Login Manual untuk Mobile/Docs"""
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    
    access, refresh = create_token_pair(user.id)
    return {"access": access, "refresh": refresh}

@api_v2.post("/auth/token-refresh", response=TokenResponseSchema, auth=None)
def mobile_token_refresh(request, data: MobileRefreshSchema):
    """Endpoint Refresh Token Manual"""
    _, pub_key = get_rsa_keys()
    candidates = []
    if pub_key: candidates.append({"key": pub_key, "algo": "RS256"})
    candidates.append({"key": settings.SECRET_KEY, "algo": "HS256"})

    user_id = None
    for opt in candidates:
        try:
            payload = jwt.decode(data.refresh, opt["key"], algorithms=[opt["algo"]])
            if payload.get("type") == "refresh":
                user_id = payload.get("user_id")
                break
        except: pass

    if not user_id:
        raise HttpError(401, "Refresh token tidak valid")

    access, refresh = create_token_pair(user_id)
    return {"access": access, "refresh": refresh}

# ==========================================
# 5. BUSINESS ENDPOINTS
# ==========================================

@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search: qs = qs.filter(username__icontains=search)
    return qs

@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")
    
    qs = CourseMember.objects.filter(user_id=user)
    results = [{"id": m.id, "user_id": user.id, "course_id": m.course_id_id} for m in qs]
    return results

@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    try:
        course_obj = Course.objects.get(pk=id)
    except Course.DoesNotExist:
        raise HttpError(404, "Course tidak ditemukan")

    if CourseMember.objects.filter(user_id=user, course_id=course_obj).exists():
        raise HttpError(400, "Kamu sudah terdaftar di course ini!")

    enrollment = CourseMember.objects.create(user_id=user, course_id=course_obj)
    return {"id": enrollment.id, "user_id": user.id, "course_id": course_obj.id}

@api_v2.post("/comments/", response=SuccessOut, auth=apiAuth) 
def post_comment(request, data: CommentIn):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    try:
        content = CourseContent.objects.get(pk=data.content_id)
    except CourseContent.DoesNotExist:
        raise HttpError(404, "Konten tidak ditemukan")

    member_qs = CourseMember.objects.filter(user_id=user, course_id=content.course_id)
    if not member_qs.exists():
        raise HttpError(400, "Tidak boleh komentar di sini (Belum Enroll)")

    comment = Comment.objects.create(
        comment=data.comment, 
        member_id=member_qs.first(), 
        content_id=content
    )
    return {"success": True, "comment_id": comment.id}

@api_v2.get("/content/{id}/comments/", response=List[CommentOut])
@paginate(CustomPagination)
def list_comments(request, id: int):
    qs = Comment.objects.filter(content_id=id).select_related("member_id__user_id")
    results = []
    for item in qs:
        results.append({
            "id": item.id,
            "comment": item.comment,
            "user_id": item.member_id.user_id.id, 
            "content_id": id
        })
    return results

@api_v2.get("/courses", response=List[CourseSchema])
@paginate(CustomPagination)
def list_courses(request, search: str = Query(None), price: str = Query(None), sort: str = Query("id")):
    queryset = Course.objects.all()
    if search: queryset = queryset.filter(name__icontains=search)
    if price: queryset = queryset.filter(price__iexact=price)
    if sort in ["id", "name", "price"]: queryset = queryset.order_by(sort)
    return queryset