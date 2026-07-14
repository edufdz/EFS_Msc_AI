# Annotation Protocol — Ground-Truth Validation

You will see anonymised WhatsApp support conversations, in order, WITHOUT
any automated labels. For each conversation answer:

1. did_fail — Did the agent fail this customer?
   - "yes": the customer was left unserved, misinformed, or had to fight the agent
   - "partial": the issue was eventually served but with real friction caused by the agent
   - "no": the agent served the customer adequately
2. categories — If yes/partial, every category that applies (see definitions).
3. note — One sentence on the decisive evidence (optional but encouraged).

Rules:
- Judge ONLY from the transcript and its visible metadata (status, counts).
- Template/system notifications are not agent failures by themselves.
- Delivery failures count when the transcript shows sends that never reached
  the customer.
- When torn between "no" and "partial", ask: would this customer complain
  about the bot? If plausibly yes, choose "partial".

## Category definitions

- **comprehension**: The agent did not understand what the customer was asking (wrong topic, generic replies, re-asking for provided info).
- **resolution**: The agent understood but could not resolve the issue; the customer demanded a human.
- **data_gap**: The agent's logic was right but backend data (orders/warranty/cost) was missing or incomplete.
- **loop_stall**: The conversation circled without progress (repeated questions or answers).
- **delivery_infra**: Messages failed to reach the customer (WhatsApp/API delivery errors).
- **missed_escalation**: The customer expressed frustration or asked for help but the agent did not escalate or change behaviour.
- **silent_abandonment**: The customer stopped responding with no resolution and no escalation.
- **hallucination**: The agent gave incorrect information (wrong price, status, or process).
