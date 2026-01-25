"""
URL configuration for cyoa_server project.
"""
from django.urls import path, include
from game import chat_views
from game import stt_views

urlpatterns = [
    # Home page
    path('', chat_views.home_page, name='home'),
    
    # Chat interface
    path('chat/', chat_views.chat_page, name='chat_page'),
    path('chat/api/new', chat_views.chat_api_new_conversation, name='chat_api_new'),
    path('chat/api/send', chat_views.chat_api_send_message, name='chat_api_send'),
    path('chat/api/conversation/<str:conversation_id>', chat_views.chat_api_get_conversation, name='chat_api_get'),
    path('chat/api/conversations', chat_views.chat_api_list_conversations, name='chat_api_list'),
    path('chat/api/delete/<str:conversation_id>', chat_views.chat_api_delete_conversation, name='chat_api_delete'),
    
    # STT (Speech-to-Text) API
    path('api/stt/upload', stt_views.stt_upload, name='stt_upload'),
    path('api/stt/transcribe', stt_views.stt_transcribe, name='stt_transcribe'),
    path('api/stt/recording/<str:recording_id>', stt_views.stt_recording_status, name='stt_recording_status'),
    path('api/stt/discard', stt_views.stt_discard, name='stt_discard'),
    
    # Admin interface
    path('admin/', include(('game.admin_urls', 'app'), namespace='admin')),
]
