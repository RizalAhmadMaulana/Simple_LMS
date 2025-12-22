from typing import Any, List, Optional
from ninja import NinjaAPI, Schema, Query
from ninja.pagination import PaginationBase, paginate
from ninja_simple_jwt.auth.views.api import mobile_auth_router
from .models import User, Course, CourseMember, CourseContent, Comment
from .throttling import SimpleRateThrottle
from .apiv2_schemas import CourseSchema, CourseMemberOut
from django.shortcuts import get_object_or_404
from ninja.errors import HttpError

# ======================
# Response Schemas
# ======================
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

# ======================
# Custom Pagination
# ======================
class CustomPagination(PaginationBase):
    class Input(Schema):
        skip: int = 0
        limit: int = 5

    class Output(Schema):
        items: List[Any]
        total: int
        per_page: int

    def paginate_queryset(self, queryset, pagination: Input, **params):
        skip = pagination.skip
        limit = pagination.limit
        
        if isinstance(queryset, list):
            total = len(queryset)
        else:
            total = queryset.count()
            
        return {
            "items": queryset[skip : skip + limit],
            "total": total,
            "per_page": limit,
        }

# ======================
# Ninja API instance v2
# ======================
api_v2 = NinjaAPI(
    title="SimpleLMS API v2",
    version="2.0.0",
    throttle=SimpleRateThrottle(),
    urls_namespace="api_v2"
)

# JWT auth router
api_v2.add_router("/auth/", mobile_auth_router)
apiAuth = mobile_auth_router.auth

# ======================
# Endpoints
# ======================

# 1. List users (paginated + optional search)
@api_v2.get("/users", response=List[UserOut])
@paginate(CustomPagination)
def list_users(request, search: Optional[str] = None):
    qs = User.objects.all()
    if search:
        qs = qs.filter(username__icontains=search)
    return qs

# 2. My Courses (logged in user)
@api_v2.get("/mycourses/", response=List[CourseMemberOut], auth=apiAuth)
@paginate(CustomPagination)
def my_courses(request):
    user_id = request.user.id
    qs = CourseMember.objects.filter(user_id=user_id).select_related("course_id")

    # Mapping ke List of Dict untuk menghindari error Pydantic Integer 
    results = []
    for member in qs:
        results.append({
            "id": member.id,
            "user_id": user_id,            
            "course_id": member.course_id.id 
        })
    
    return results

# 3. Enroll course
@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user_id = request.user.id
    user_obj = User.objects.get(pk=user_id)

    try:
        course_obj = Course.objects.get(pk=id)
    except Course.DoesNotExist:
        raise HttpError(404, "Course tidak ditemukan")

    if CourseMember.objects.filter(user_id=user_obj, course_id=course_obj).exists():
        raise HttpError(400, "Kamu sudah terdaftar di course ini!")

    enrollment = CourseMember.objects.create(user_id=user_obj, course_id=course_obj)

    return {
        "id": enrollment.id,
        "user_id": user_obj.id,   
        "course_id": course_obj.id  
    }

# 4. Post comment
@api_v2.post("/comments/", response=SuccessOut, auth=apiAuth)
def post_comment(request, data: CommentIn):
    user = request.user
    content = CourseContent.objects.filter(pk=data.content_id).first()
    if not content:
        return {"success": False, "comment_id": None, "error": "Content not found"}

    # Pastikan user ikut course
    member = CourseMember.objects.filter(user_id=user, course_id=content.course_id)
    if not member.exists():
        return {"success": False, "comment_id": None, "error": "Tidak boleh komentar di sini"}

    comment = Comment.objects.create(comment=data.comment, user_id=user, content_id=content)
    return {"success": True, "comment_id": comment.id}

# 5. List comments for a content (paginated)
@api_v2.get("/content/{id}/comments/", response=List[CommentOut])
@paginate(CustomPagination)
def list_comments(request, id: int):
    qs = Comment.objects.filter(content_id=id)
    return qs

# 6. List Courses (Filtering & Sorting)
@api_v2.get("/courses", response=List[CourseSchema])
@paginate(CustomPagination)
def list_courses(
    request,
    search: str = Query(None),
    price: str = Query(None),
    sort: str = Query("id"),
):
    queryset = Course.objects.all()

    # FILTERING
    if search:
        queryset = queryset.filter(name__icontains=search)

    if price:
        queryset = queryset.filter(price__iexact=price)

    # SORTING
    allowed_sort = ["id", "name", "price"]
    if sort in allowed_sort:
        queryset = queryset.order_by(sort)

    return queryset