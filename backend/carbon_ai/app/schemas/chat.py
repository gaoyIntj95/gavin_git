from datetime import datetime
from pydantic import BaseModel, Field


class ChatAskRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    question: str = Field(..., min_length=1)
    mode: str = Field(default="auto", pattern=r"^(auto|rag|agent)$")
    project_id: int | None = Field(default=None)


class ChatAskResponse(BaseModel):
    answer: str
    references: list[str]
    mode: str = "rag"
    chart: dict | None = None


class ChatMessage(BaseModel):
    question: str
    answer: str
    references: list[str]
    mode: str = "rag"
    project_id: int | None = None
    created_at: datetime
    chart: dict | None = None


class ChatSessionResponse(BaseModel):
    messages: list[ChatMessage]


class ChatSessionItem(BaseModel):
    session_id: str
    name: str
    mode: str = "rag"
    project_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionItem]


class ChatSessionCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="新会话", max_length=255)
    mode: str = Field(default="rag", pattern=r"^(rag|agent)$")
    project_id: int | None = Field(default=None)


class ChatSessionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    project_id: int | None = Field(default=None)


class KnowledgeUploadResponse(BaseModel):
    document_id: int
    filename: str
    chunk_count: int
    status: str
    file_url: str | None = None


class KnowledgeDocumentItem(BaseModel):
    id: int
    filename: str
    file_type: str
    object_key: str | None = None
    file_url: str | None = None
    file_size: int = 0
    storage_provider: str = "minio"
    chunk_count: int
    status: str
    created_at: datetime


class KnowledgeListResponse(BaseModel):
    documents: list[KnowledgeDocumentItem]


class QuickQuestionItem(BaseModel):
    id: int
    question: str
    category: str


class QuickQuestionListResponse(BaseModel):
    questions: list[QuickQuestionItem]
