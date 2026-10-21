"""Allowlisted live-data operations backed by Spring Boot.

The chat router can call only names in TOOL_NAMES. Never accept arbitrary
SQL, URL paths, or tool names from a user message.
"""

TOOL_NAMES = frozenset({
    "get_expired_contracts",
    "get_expiring_certificates",
    "list_vessels",
})

# Kept for compatibility with any existing Bedrock Converse client elsewhere
# in the service. Direct chat routing in ChatService does not use these schemas
# to generate or rewrite answers.
BEDROCK_TOOL_CONFIG = [
    {
        "toolSpec": {
            "name": "get_expired_contracts",
            "description": "Retrieve expired or expiring contracts within a day window.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3650,
                            "description": "Number of days to look ahead.",
                        }
                    },
                    "required": ["days"],
                    "additionalProperties": False,
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_expiring_certificates",
            "description": "Retrieve crew certificates expiring within a day window.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 3650,
                            "description": "Number of days to look ahead.",
                        }
                    },
                    "required": ["days"],
                    "additionalProperties": False,
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "list_vessels",
            "description": "Retrieve the vessel list from the Java API.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                }
            },
        }
    },
]
