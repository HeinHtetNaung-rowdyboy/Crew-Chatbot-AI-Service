import boto3
from botocore.config import Config
from redis.asyncio import Redis

from src.core.config import Settings
from src.providers.bedrock_rag_client import BedrockRagClient
from src.providers.bedrock_tool_client import BedrockToolClient
from src.repositories.redis_conversation_store import RedisConversationStore
from src.retrieval.knowledge_base import KnowledgeBaseRetriever
from src.services.chat_service import ChatService


class Resources:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis = None
        self.bedrock_client = None
        self.bedrock_runtime_client = None
        self.retriever = None
        self.rag_client = None
        self.tool_client = None
        self.chat_service = None

    async def start(self):
        # Initialize Redis
        self.redis = Redis.from_url(
            self.settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=10,
            health_check_interval=30,
        )
        await self.redis.ping()

        # Initialize AWS clients
        session = boto3.Session(region_name=self.settings.aws_region)

        bedrock_config = Config(
            connect_timeout=3,
            read_timeout=90,
            retries={"max_attempts": 3, "mode": "standard"},
        )

        # Used by Knowledge Bases Retrieve and RetrieveAndGenerate.
        self.bedrock_client = session.client(
            "bedrock-agent-runtime",
            config=bedrock_config,
        )

        # Used by Bedrock Converse tool calling for Spring Boot APIs.
        self.bedrock_runtime_client = session.client(
            "bedrock-runtime",
            config=bedrock_config,
        )

        store = RedisConversationStore(
            redis=self.redis,
            ttl_seconds=self.settings.chat_memory_ttl_seconds,
            max_qa_pairs=self.settings.chat_memory_max_qa_pairs,
            lock_timeout_seconds=self.settings.chat_lock_timeout_seconds,
            lock_wait_seconds=self.settings.chat_lock_wait_seconds,
        )

        self.retriever = KnowledgeBaseRetriever(
            client=self.bedrock_client,
            knowledge_base_id=self.settings.knowledge_base_id,
            number_of_results=5,
        )

        # Generates grounded answers from the Knowledge Base using
        # GENERATION_PROMPT in src/prompts/generation_prompt.py.
        self.rag_client = BedrockRagClient(
            client=self.bedrock_client,
            knowledge_base_id=self.settings.knowledge_base_id,
            model_arn=self.settings.model_arn,
        )

        # Preserves the existing Java API tool-calling/authentication flow.
        self.tool_client = BedrockToolClient(
            client=self.bedrock_runtime_client,
            model_id=self.settings.model_arn,
            java_api_base_url=self.settings.java_api_base_url,
        )

        self.chat_service = ChatService(
            settings=self.settings,
            store=store,
            retriever=self.retriever,
            tool_client=self.tool_client,
            rag_client=self.rag_client,
        )

    async def close(self):
        if self.redis is not None:
            await self.redis.aclose()

        for client in (self.bedrock_client, self.bedrock_runtime_client):
            if client is not None:
                close = getattr(client, "close", None)
                if close:
                    close()
