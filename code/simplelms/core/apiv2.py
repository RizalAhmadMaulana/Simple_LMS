# File: docker_django/code/simplelms/core/apiv2.py

from typing import Any, List, Optional
from ninja import NinjaAPI, Schema, Query
from ninja.pagination import PaginationBase, paginate
from ninja_simple_jwt.auth.views.api import mobile_auth_router
from .models import User, Course, CourseMember, CourseContent, Comment
from .throttling import SimpleRateThrottle
from .apiv2_schemas import CourseSchema

# ======================
# Response Schemas
# ======================
class UserOut(Schema):
    id: int
    username: str
    email: str

class CourseMemberOut(Schema):
    id: int
    user_id: int
    course_id: int

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
        return {
            "items": queryset[skip : skip + limit],
            "total": queryset.count(),
            "per_page": limit,
        }

# ======================
# Ninja API instance v2
# ======================
api_v2 = NinjaAPI(
    title="SimpleLMS API v2",
    version="2.0.0",
    throttle=SimpleRateThrottle(),   # <--- Throttling Aktif Global
    urls_namespace="api_v2" # Penting agar tidak bentrok dengan v1
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
    qs = CourseMember.objects.filter(user_id=user_id).select_related("course_id", "user_id")
    return qs

# 3. Enroll course
@api_v2.post("/course/{id}/enroll/", response=CourseMemberOut, auth=apiAuth)
def enroll_course(request, id: int):
    user = request.user
    try:
        course = Course.objects.get(pk=id)
    except Course.DoesNotExist:
        return {"error": "Course not found"}
    
    enrollment, created = CourseMember.objects.get_or_create(user_id=user, course_id=course)
    return enrollment

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