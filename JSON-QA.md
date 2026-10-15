### Test Case 1 — Get All Registered Vessels

**Request JSON**

```json
{
  "requestId": "tool-test-001",
  "conversationId": "tool-test-001",
  "message": "Show me all registered vessels."
}
```

**Expected tool:** `list_vessels`

**Expected Java API call:**

```http
GET {{crew_prod}}/api/vessels
```

**Expected result:** MarineOn summarizes the registered vessels returned by the Java API. It should not interpret the request as asking for a current vessel.

---

### Test Case 2 — Find Contracts Expiring Within 60 Days

**Request JSON**

```json
{
  "requestId": "tool-test-002",
  "conversationId": "tool-test-002",
  "message": "Which crew contracts will expire in the next 60 days?"
}
```

**Expected tool:** `get_expiring_contracts`

**Expected Java API call:**

```http
GET {{base_url}}/api/dashboard/expired-contracts?days=60
```

**Expected result:** MarineOn summarizes the contracts scheduled to expire within the next 60 days.

---

### Test Case 3 — Find Certificates Expiring Within 100 Days

**Request JSON**

```json
{
  "requestId": "tool-test-003",
  "conversationId": "tool-test-003",
  "message": "Which crew certificates will expire in the next 100 days?"
}
```

**Expected tool:** `get_expiring_certifications`

**Expected Java API call:**

```http
GET {{base_url}}/api/dashboard/expiring-certificates?days=100
```

**Expected result:** MarineOn summarizes the certificates scheduled to expire within the next 100 days.

---

### Verification Checklist

- [ ] `get_all_vessels` is selected for vessel-list requests.
- [ ] `get_expiring_contracts` is selected for contract-expiry requests.
- [ ] `get_expiring_certifications` is selected for certificate-expiry requests.
- [ ] Each tool calls the correct Java API endpoint.
- [ ] The requested day range is passed correctly.
- [ ] The response contains actual API data rather than unintended mock data.
- [ ] The chat API returns HTTP `200 OK` with the correct request and conversation IDs.
