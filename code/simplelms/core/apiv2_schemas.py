from ninja import Schema

class CourseSchema(Schema):
    id: int
    name: str
    description: str
    price: int

class CourseMemberOut(Schema):
    id: int
    user_id: int   
    course_id: int  