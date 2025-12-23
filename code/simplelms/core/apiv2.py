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
# 1. HYBRID AUTHENTICATION (ANTI 401)
# ==========================================
def get_rsa_keys():
    """Mencoba membaca kunci RSA jika ada"""
    try:
        private_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pem')
        public_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pub')
        
        priv, pub = None, None
        if os.path.exists(private_path):
            with open(private_path, 'rb') as f: priv = f.read()
        if os.path.exists(public_path):
            with open(public_path, 'rb') as f: pub = f.read()
            
        return priv, pub
    except:
        return None, None

def create_token_pair(user_id):
    """Membuat token, prioritas pakai RSA, fallback ke SECRET_KEY"""
    priv_key, _ = get_rsa_keys()
    
    # Tentukan Key dan Algo untuk ENCODE
    if priv_key:
        key = priv_key
        algo = "RS256"
    else:
        key = settings.SECRET_KEY
        algo = "HS256"

    # Buat Payload
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

    access_token = jwt.encode(payload_access, key, algorithm=algo)
    refresh_token = jwt.encode(payload_refresh, key, algorithm=algo)

    # Convert bytes to string (untuk kompatibilitas)
    if isinstance(access_token, bytes): access_token = access_token.decode('utf-8')
    if isinstance(refresh_token, bytes): refresh_token = refresh_token.decode('utf-8')
    
    return access_token, refresh_token

class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        _, pub_key = get_rsa_keys()
        
        # --- PERCOBAAN 1: Validasi pakai RSA (RS256) ---
        if pub_key:
            user = self.try_decode(token, pub_key, "RS256")
            if user: return user

        # --- PERCOBAAN 2: Validasi pakai SECRET_KEY (HS256) ---
        # Ini penting kalau RSA gagal atau tidak ada
        user = self.try_decode(token, settings.SECRET_KEY, "HS256")
        if user: return user
        
        # Kalau dua-duanya gagal, berarti emang 401
        return None

    def try_decode(self, token, key, algo):
        try:
            payload = jwt.decode(token, key, algorithms=[algo])
            if payload.get("type") != "access":
                return None
            user_id = payload.get("user_id")
            return User.objects.get(pk=user_id)
        except:
            return None

# Instansiasi Auth
apiAuth = CustomJwtAuth()

# ==========================================
# 2. NINJA API INSTANCE
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
# 4. ENDPOINTS
# ==========================================

# --- AUTH ---
@api_v2.post("/auth/sign-in", response=TokenResponseSchema, auth=None)
def mobile_sign_in(request, data: MobileSignInSchema):
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    
    access, refresh = create_token_pair(user.id)
    return {"access": access, "refresh": refresh}

@api_v2.post("/auth/token-refresh", response=TokenResponseSchema, auth=None)
def mobile_token_refresh(request, data: MobileRefreshSchema):
    # Coba decode refresh token dengan strategi hybrid juga
    user_id = None
    _, pub_key = get_rsa_keys()
    
    # Coba RS256
    if pub_key:
        try:
            payload = jwt.decode(data.refresh, pub_key, algorithms=["RS256"])
            if payload.get("type") == "refresh": user_id = payload.get("user_id")
        except: pass
    
    # Coba HS256 jika belum dapat
    if not user_id:
        try:
            payload = jwt.decode(data.refresh, settings.SECRET_KEY, algorithms=["HS256"])
            if payload.get("type") == "refresh": user_id = payload.get("user_id")
        except: pass

    if not user_id:
        raise HttpError(401, "Refresh token tidak valid atau expired")

    access, refresh = create_token_pair(user_id)
    return {"access": access, "refresh": refresh}

@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search: qs = qs.filter(username__icontains=search)
    return qs

# --- PROTECTED ENDPOINTS (FIXED) ---

@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized: Token Invalid")
    
    # Filter menggunakan objek user yang didapat dari auth
    qs = CourseMember.objects.filter(user_id=user)
    
    results = []
    for member in qs:
        results.append({
            "id": member.id,
            "user_id": user.id,            
            "course_id": member.course_id_id 
        })
    return results

@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized: Token Invalid")

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
    if not user: raise HttpError(401, "Unauthorized: Token Invalid")

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

# --- PUBLIC ENDPOINTS ---

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