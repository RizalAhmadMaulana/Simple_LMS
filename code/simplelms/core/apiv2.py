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
# 1. UNIVERSAL AUTHENTICATION (DEBUG MODE)
# ==========================================

def get_rsa_keys():
    """Membaca kunci RSA jika tersedia"""
    priv, pub = None, None
    try:
        priv_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pem')
        pub_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pub')
        
        if os.path.exists(priv_path):
            with open(priv_path, 'rb') as f: priv = f.read()
        if os.path.exists(pub_path):
            with open(pub_path, 'rb') as f: pub = f.read()
    except Exception as e:
        print(f"[KEY LOAD ERROR] {e}")
    return priv, pub

def create_token_pair(user_id):
    """Membuat token (Prioritas RSA, Fallback HS256)"""
    priv_key, _ = get_rsa_keys()
    
    if priv_key:
        key = priv_key
        algo = "RS256"
    else:
        key = settings.SECRET_KEY
        algo = "HS256"

    # Payload
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

    # Encode
    access = jwt.encode(payload_access, key, algorithm=algo)
    refresh = jwt.encode(payload_refresh, key, algorithm=algo)
    
    # Ensure String
    if isinstance(access, bytes): access = access.decode('utf-8')
    if isinstance(refresh, bytes): refresh = refresh.decode('utf-8')
    
    return access, refresh

class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        # 1. Siapkan Kandidat Key
        _, pub_key = get_rsa_keys()
        
        candidates = []
        # Opsi A: Pakai RSA Public Key (RS256)
        if pub_key:
            candidates.append({"key": pub_key, "algo": "RS256", "name": "RSA Public Key"})
        
        # Opsi B: Pakai Django Secret Key (HS256) -> Jaga-jaga kalau RSA gagal/tidak ada
        candidates.append({"key": settings.SECRET_KEY, "algo": "HS256", "name": "Django Secret"})

        # 2. Coba Decode satu per satu
        for opt in candidates:
            try:
                payload = jwt.decode(token, opt["key"], algorithms=[opt["algo"]])
                
                # Cek Tipe Token
                if payload.get("type") != "access":
                    print(f"[AUTH FAIL] Token tipe '{payload.get('type')}' bukan 'access' (via {opt['name']})")
                    continue # Coba key berikutnya

                user_id = payload.get("user_id")
                user = User.objects.get(pk=user_id)
                
                # BERHASIL!
                # print(f"[AUTH SUCCESS] User {user.username} via {opt['name']}")
                return user

            except jwt.ExpiredSignatureError:
                print(f"[AUTH FAIL] Token Expired via {opt['name']}")
            except jwt.DecodeError:
                # Ini wajar jika kita mencoba Key yang salah (misal coba RSA padahal token HS256)
                # print(f"[AUTH INFO] Gagal decode via {opt['name']} (mungkin beda key)")
                pass
            except User.DoesNotExist:
                print(f"[AUTH FAIL] User ID {payload.get('user_id')} tidak ditemukan di DB")
            except Exception as e:
                print(f"[AUTH ERROR] Error via {opt['name']}: {e}")

        # Jika semua loop selesai dan tidak ada return, berarti GAGAL TOTAL
        print("[AUTH FINAL] Token ditolak oleh semua metode.")
        return None

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
    # Coba decode refresh token (Hybrid Check)
    user_id = None
    _, pub_key = get_rsa_keys()
    
    candidates = []
    if pub_key: candidates.append({"key": pub_key, "algo": "RS256"})
    candidates.append({"key": settings.SECRET_KEY, "algo": "HS256"})

    for opt in candidates:
        try:
            payload = jwt.decode(data.refresh, opt["key"], algorithms=[opt["algo"]])
            if payload.get("type") == "refresh":
                user_id = payload.get("user_id")
                break
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

# --- PROTECTED (FIXED) ---
@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user = request.auth
    if not user: raise HttpError(401, "Unauthorized")
    
    # Ambil data CourseMember berdasarkan user yang login
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

# --- PUBLIC ---
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