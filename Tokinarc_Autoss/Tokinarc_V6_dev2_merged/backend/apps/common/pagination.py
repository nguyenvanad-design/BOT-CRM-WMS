"""Phân trang mặc định — cho phép client xin page_size lớn hơn (vd bản đồ kho)."""
from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'   # ?page_size=1000 để lấy 1 lượt
    max_page_size = 2000
