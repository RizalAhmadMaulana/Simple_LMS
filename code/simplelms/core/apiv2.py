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
# 1. HELPER FUNCTIONS (TOKEN GENERATOR)
# ==========================================
def get_signing_key(access=True):
    """Membaca Private Key untuk encode atau Public Key untuk decode"""
    # Untuk Encode (membuat token), kita butuh Private Key (PEM)
    filename = 'jwt-signing.pem'
    algorithm = "RS256"
    
    key_path = os.path.join(settings.BASE_DIR, filename)
    
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            return f.read(), algorithm
    else:
        # Fallback ke SECRET_KEY (HS256)
        return settings.SECRET_KEY, "HS256"

def get_verification_key():
    """Membaca Public Key untuk verifikasi token"""
    filename = 'jwt-signing.pub'
    algorithm = "RS256"
    key_path = os.path.join(settings.BASE_DIR, filename)
    
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            return f.read(), algorithm
    else:
        return settings.SECRET_KEY, "HS256"

def create_token_pair(user_id):
    """Membuat Access Token dan Refresh Token"""
    key, algo = get_signing_key()
    
    # Access Token (exp 1 hari)
    access_payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "iat": datetime.datetime.utcnow(),
        "type": "access"
    }
    access_token = jwt.encode(access_payload, key, algorithm=algo)
    
    # Refresh Token (exp 7 hari)
    refresh_payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
        "iat": datetime.datetime.utcnow(),
        "type": "refresh"
    }
    refresh_token = jwt.encode(refresh_payload, key, algorithm=algo)

    # Pastikan string (kompatibilitas versi pyjwt)
    if isinstance(access_token, bytes): access_token = access_token.decode('utf-8')
    if isinstance(refresh_token, bytes): refresh_token = refresh_token.decode('utf-8')
    
    return access_token, refresh_token

# ==========================================
# 2. CUSTOM AUTHENTICATION
# ==========================================
class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        try:
            key, algo = get_verification_key()
            # Decode Token
            payload = jwt.decode(token, key, algorithms=[algo])
            
            # Validasi tipe token
            if payload.get("type") != "access":
                return None

            user_id = payload.get("user_id")
            if user_id:
                return User.objects.get(pk=user_id)
        except Exception:
            return None

apiAuth = CustomJwtAuth()

# ==========================================
# 3. NINJA API SETUP
# ==========================================
api_v2 = NinjaAPI(
    title="SimpleLMS API v2",
    version="2.0.0",
    throttle=SimpleRateThrottle(),
    urls_namespace="api_v2"
)

# ==========================================
# 4. SCHEMAS (AUTH & DATA)
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

# ==========================================
# 5. AUTH ENDPOINTS (MANUAL IMPLEMENTATION)
# ==========================================

# Endpoint: Mobile Sign In
@api_v2.post("/auth/sign-in", response=TokenResponseSchema, auth=None)
def mobile_sign_in(request, data: MobileSignInSchema):
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    
    access, refresh = create_token_pair(user.id)
    return {"access": access, "refresh": refresh}

# Endpoint: Mobile Token Refresh
@api_v2.post("/auth/token-refresh", response=TokenResponseSchema, auth=None)
def mobile_token_refresh(request, data: MobileRefreshSchema):
    try:
        key, algo = get_verification_key()
        payload = jwt.decode(data.refresh, key, algorithms=[algo])
        
        if payload.get("type") != "refresh":
            raise HttpError(400, "Token tidak valid (bukan refresh token)")
            
        user_id = payload.get("user_id")
        # Generate pasangan token baru
        access, refresh = create_token_pair(user_id)
        return {"access": access, "refresh": refresh}
        
    except jwt.ExpiredSignatureError:
        raise HttpError(401, "Refresh token expired")
    except Exception:
        raise HttpError(401, "Refresh token tidak valid")

# ==========================================
# 6. BUSINESS ENDPOINTS
# ==========================================
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

@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search:
        qs = qs.filter(username__icontains=search)
    return qs

@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")
    
    qs = CourseMember.objects.filter(user_id=user).select_related("course_id")
    results = []
    for member in qs:
        results.append({
            "id": member.id,
            "user_id": user.id,            
            "course_id": member.course_id.id 
        })
    return results

@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    course_obj = get_object_or_404(Course, pk=id)

    if CourseMember.objects.filter(user_id=user, course_id=course_obj).exists():
        raise HttpError(400, "Kamu sudah terdaftar di course ini!")

    enrollment = CourseMember.objects.create(user_id=user, course_id=course_obj)
    return {"id": enrollment.id, "user_id": user.id, "course_id": course_obj.id}

@api_v2.post("/comments/", response=SuccessOut, auth=apiAuth) 
def post_comment(request, data: CommentIn):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")

    content = get_object_or_404(CourseContent, pk=data.content_id)
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