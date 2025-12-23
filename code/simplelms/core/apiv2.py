import jwt
import datetime
import os
from typing import Any, List, Optional
from ninja import NinjaAPI, Schema, Query
from ninja.pagination import PaginationBase, paginate
from ninja_simple_jwt.auth.views.api import mobile_auth_router
from ninja.security import HttpBearer
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from ninja.errors import HttpError
from .models import User, Course, CourseMember, CourseContent, Comment
from .throttling import SimpleRateThrottle
from .apiv2_schemas import CourseSchema, CourseMemberOut

# ==========================================
# 1. AUTHENTICATION HELPERS (KUNCI PASTI SAMA)
# ==========================================
def get_exact_key():
    """
    Satu fungsi pusat untuk mengambil Kunci.
    Memastikan Create Token & Verify Token selalu pakai kunci yang sama.
    """
    priv_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pem')
    pub_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pub')
    
    # Prioritas 1: RSA Keys (untuk Docker/Prod)
    if os.path.exists(priv_path) and os.path.exists(pub_path):
        with open(priv_path, 'rb') as f: priv = f.read()
        with open(pub_path, 'rb') as f: pub = f.read()
        return priv, pub, "RS256"
    
    # Prioritas 2: Secret Key (untuk Lokal/Test)
    return settings.SECRET_KEY, settings.SECRET_KEY, "HS256"

def create_access_token(user_id):
    priv_key, _, algo = get_exact_key()
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "type": "access"
    }
    token = jwt.encode(payload, priv_key, algorithm=algo)
    if isinstance(token, bytes): token = token.decode('utf-8')
    return token

class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        # Bersihkan "Bearer " agar Test & Swagger sama-sama bisa masuk
        if token.lower().startswith("bearer "):
            token = token.split(" ")[1]

        _, pub_key, algo = get_exact_key()
        
        try:
            # Decode dengan kunci yang PASTI cocok
            payload = jwt.decode(token, pub_key, algorithms=[algo])
            
            if payload.get("type") == "access":
                user_id = payload.get("user_id")
                return User.objects.get(pk=user_id)
        except:
            return None
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
# Kita buat Schema Login sendiri agar tidak bergantung pada library yang error
class ManualLoginSchema(Schema):
    username: str
    password: str

class TokenResponseSchema(Schema):
    access: str

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

# Endpoint Login Manual (PENGGANTI ROUTER YANG ERROR)
# Ini yang bikin Test & Endpoint Manual jalan dua-duanya
@api_v2.post("/auth/sign-in", response=TokenResponseSchema, auth=None)
def sign_in(request, data: ManualLoginSchema):
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    
    token = create_access_token(user.id)
    return {"access": token}

# ---
# ENDPOINTS LAIN (Tetap sama, cuma pakai apiAuth & request.auth)
# ---

@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search: qs = qs.filter(username__icontains=search)
    return qs

@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth # Pasti terisi User object
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
        raise HttpError(400, "Tidak boleh komentar di sini")

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