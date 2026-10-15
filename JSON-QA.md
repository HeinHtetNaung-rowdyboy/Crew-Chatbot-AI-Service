## Testing MarineOn Business Tools

### 1. Prerequisites

Before running the tests, make sure:

- The FastAPI service is running.
- Redis is connected.
- AWS credentials and Amazon Bedrock access are configured.
- The business-tool mock handlers are enabled.
- You have configured `INTERNAL_API_TOKEN` in your environment.

Start the service:

```powershell
.\venv\Scripts\Activate.ps1
uvicorn src.app:app --reload --log-level info
```

### 2. API Endpoint

**Method:** `POST`

**URL:**

```text
http://127.0.0.1:8000/internal/v1/chat
```

**Headers:**

```http
Content-Type: application/json
X-Internal-Service-Token: YOUR_INTERNAL_API_TOKEN
```

Replace `YOUR_INTERNAL_API_TOKEN` with the token configured in your environment.

---

### 3. Test Case 1 — Get Current Vessel

**Purpose:** Verify that MarineOn identifies a question about the user's current vessel and selects `get_current_vessel`.

**Request JSON:**

```json
{
  "requestId": "tool-test-001",
  "conversationId": "tool-test-001",
  "message": "get all registered vessel?",
}
```

**Expected tool:**

```text
get_current_vessel
```

**Example response:**

```json
{
  "requestId": "tool-test-001",
  "conversationId": "tool-test-001",
  "answer": "Which contracts will expire in the next 60 days",
  "citations": [],
  "latencySeconds": 1.234
}
```



---

### 4. Test Case 2 — Find Expiring Certifications

**Purpose:** Verify that MarineOn selects `get_expiring_certifications` when the user asks about upcoming certification expirations.

**Request JSON:**

```json
{
  "requestId": "tool-test-002",
  "conversationId": "tool-test-002",
  "message": "Which certifications are expiring in the next 30 days?",
}
```

**Expected tool:**

```text
get_expiring_certifications
```

**Expected tool arguments:**

```json
{
  "daysAhead": 30
}
```

**Example response:**

```json
{
  "requestId": "tool-test-002",
  "conversationId": "tool-test-002",
  "answer": "The mock certification data includes the following upcoming expirations:\n\n1. Medical Certificate (C-1001): 2026-10-25\n2. Basic Safety Training (C-1002): 2026-11-05",
  "citations": [],
  "latencySeconds": 1.456
}
```

**Important:** The current mock handler contains fixed sample certification records. Confirm that it filters the records using `daysAhead` before treating this test as a date-accurate result. The example above illustrates the mock data, not a guarantee that both records fall within the requested 30-day window.



---

### 6. Verify the Terminal Logs

When you submit a request, check the terminal running Uvicorn. The current implementation should print logs similar to these:

```text
[CHAT] Received request ...
[CHAT] Selected tool: get_current_vessel
[BEDROCK TOOL] Starting request ...
[BEDROCK TOOL] stopReason: tool_use
[BEDROCK TOOL] Tool requested: get_current_vessel
[TOOL HANDLER] Executing get_current_vessel ...
[BEDROCK TOOL] Mock handler succeeded ...
```

The exact messages and order may vary. For each test, confirm that:

1. The correct tool is selected.
2. Bedrock requests the expected tool and arguments.
3. The mock handler executes successfully.
4. The API returns HTTP `200 OK` with the expected request and conversation IDs.

