"""Tokinarc V6.C — apps/storage/views.py — khớp V6.B.3 §3.7"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from . import services
from .models import FileObject
from .serializers import FileObjectSerializer


class UploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get('file')
        if not f:
            return Response({'detail': 'Thiếu file.', 'code': 'VALIDATION_FAILED'},
                            status=status.HTTP_400_BAD_REQUEST)
        obj = services.save_upload(
            file=f, kind=request.data.get('kind', 'misc'),
            related_kind=request.data.get('related_kind', ''),
            related_id=request.data.get('related_id', ''), user=request.user)
        return Response(FileObjectSerializer(obj).data, status=status.HTTP_201_CREATED)


class FileObjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FileObject.objects.all()
    serializer_class = FileObjectSerializer
    permission_classes = [IsAuthenticated]
