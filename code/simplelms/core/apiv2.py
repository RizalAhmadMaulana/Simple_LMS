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
# 1. CUSTOM AUTHENTICATION (BACA PUBLIC KEY)
# ==========================================
class CustomJwtAuth(HttpBearer):
    def authenticate(self, request, token):
        try:
            # Path Public Key
            key_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pub')
            
            if os.path.exists(key_path):
                with open(key_path, 'rb') as f:
                    key = f.read()
                algorithms = ["RS256"]
            else:
                # Fallback ke SECRET_KEY jika file tidak ada
                key = settings.SECRET_KEY
                algorithms = ["HS256"]

            # Decode Token
            payload = jwt.decode(token, key, algorithms=algorithms)
            
            # Ambil User dari Payload
            user_id = payload.get("user_id")
            if user_id:
                return User.objects.get(pk=user_id)
                
        except Exception:
            return None

# Instansiasi Auth
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
# 3. HELPER: CREATE TOKEN (BACA PRIVATE KEY)
# ==========================================
def create_access_token(user_id):
    key_path = os.path.join(settings.BASE_DIR, 'jwt-signing.pem')
    
    if os.path.exists(key_path):
        with open(key_path, 'rb') as f:
            key = f.read()
        algorithm = "RS256"
    else:
        key = settings.SECRET_KEY
        algorithm = "HS256"

    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
        "iat": datetime.datetime.utcnow(),
    }
    
    # Encode return bytes di versi lama, string di baru. Kita pastikan string.
    token = jwt.encode(payload, key, algorithm=algorithm)
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

# ==========================================
# 4. SCHEMAS
# ==========================================
class LoginSchema(Schema):
    username: str
    password: str

class TokenSchema(Schema):
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

# ==========================================
# 5. MANUAL LOGIN ENDPOINT (PENGGANTI ROUTER)
# ==========================================
@api_v2.post("/auth/sign-in", response=TokenSchema, auth=None)
def sign_in(request, data: LoginSchema):
    user = authenticate(username=data.username, password=data.password)
    if not user:
        raise HttpError(401, "Username atau password salah")
    
    token = create_access_token(user.id)
    return {"access": token}

# ==========================================
# 6. PAGINATION & ENDPOINTS LAINNYA
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