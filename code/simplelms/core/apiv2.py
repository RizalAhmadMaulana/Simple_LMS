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
# 1. HELPER FUNCTIONS & AUTH
# ==========================================
def get_signing_key(access=True):
    filename = 'jwt-signing.pem'
    algorithm = "RS256"
    key_path = os.path.join(settings.BASE_DIR, filename)
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            return f.read(), algorithm
    else:
        return settings.SECRET_KEY, "HS256"

def get_verification_key():
    filename = 'jwt-signing.pub'
    algorithm = "RS256"
    key_path = os.path.join(settings.BASE_DIR, filename)
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            return f.read(), algorithm
    else:
        return settings.SECRET_KEY, "HS256"

def create_token_pair(user_id):
    key, algo = get_signing_key()
    
    access_payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "iat": datetime.datetime.utcnow(),
        "type": "access"
    }
    access_token = jwt.encode(access_payload, key, algorithm=algo)
    
    refresh_payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
        "iat": datetime.datetime.utcnow(),
        "type": "refresh"
    }
    refresh_token = jwt.encode(refresh_payload, key, algorithm=algo)

    if isinstance(access_token, bytes): access_token = access_token.decode('utf-8')
    if isinstance(refresh_token, bytes): refresh_token = refresh_token.decode('utf-8')
    return access_token, refresh_token

class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        try:
            key, algo = get_verification_key()
            payload = jwt.decode(token, key, algorithms=[algo])
            if payload.get("type") != "access":
                return None
            user_id = payload.get("user_id")
            if user_id:
                return User.objects.get(pk=user_id)
        except Exception:
            return None

apiAuth = CustomJwtAuth()

api_v2 = NinjaAPI(
    title="SimpleLMS API v2",
    version="2.0.0",
    throttle=SimpleRateThrottle(),
    urls_namespace="api_v2"
)

# ==========================================
# 2. SCHEMAS
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
# 3. ENDPOINTS (FIXED MYCOURSES & ENROLL)
# ==========================================

@api_v2.post("/auth/sign-in", response=TokenResponseSchema, auth=None)
def mobile_sign_in(request, data: MobileSignInSchema):
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    access, refresh = create_token_pair(user.id)
    return {"access": access, "refresh": refresh}

@api_v2.post("/auth/token-refresh", response=TokenResponseSchema, auth=None)
def mobile_token_refresh(request, data: MobileRefreshSchema):
    try:
        key, algo = get_verification_key()
        payload = jwt.decode(data.refresh, key, algorithms=[algo])
        if payload.get("type") != "refresh":
            raise HttpError(400, "Token tidak valid")
        access, refresh = create_token_pair(payload.get("user_id"))
        return {"access": access, "refresh": refresh}
    except Exception:
        raise HttpError(401, "Refresh token expired/invalid")

@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search: qs = qs.filter(username__icontains=search)
    return qs

# === FIX 1: MY COURSES ===
@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")
    
    # Gunakan 'user_id' (nama field di model) untuk filter
    # Tapi kita ambil 'course_id_id' (raw integer) untuk response agar lebih cepat
    qs = CourseMember.objects.filter(user_id=user)
    
    results = []
    for member in qs:
        results.append({
            "id": member.id,
            "user_id": user.id,            
            "course_id": member.course_id_id # <--- Pakai _id agar tidak query ulang
        })
    return results

# === FIX 2: ENROLL COURSE ===
@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    try:
        course_obj = Course.objects.get(pk=id)
    except Course.DoesNotExist:
        raise HttpError(404, "Course tidak ditemukan")

    # Cek duplikasi dengan filter object langsung
    if CourseMember.objects.filter(user_id=user, course_id=course_obj).exists():
        raise HttpError(400, "Kamu sudah terdaftar di course ini!")

    # Buat enrollment baru
    enrollment = CourseMember.objects.create(
        user_id=user,      # Pass User Object
        course_id=course_obj # Pass Course Object
    )

    return {
        "id": enrollment.id,
        "user_id": user.id,   
        "course_id": course_obj.id  
    }

@api_v2.post("/comments/", response=SuccessOut, auth=apiAuth) 
def post_comment(request, data: CommentIn):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    try:
        content = CourseContent.objects.get(pk=data.content_id)
    except CourseContent.DoesNotExist:
        raise HttpError(404, "Konten tidak ditemukan")

    # Cek member akses
    member_qs = CourseMember.objects.filter(user_id=user, course_id=content.course_id)
    if not member_qs.exists():
        raise HttpError(400, "Tidak boleh komentar di sini (belum enroll)")

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
        # Akses user_id melalui relasi member_id -> user_id
        # Perhatikan: item.member_id adalah object CourseMember
        # item.member_id.user_id adalah object User (karena nama fieldnya user_id)
        # item.member_id.user_id.id adalah integer ID User
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