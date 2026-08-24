"""
DeepSeek via AWS Bedrock — PRIMARY MODEL for Shafanna.

WHY:
- DeepSeek on Bedrock is CHEAP ($0.14/M input, $0.28/M output for V3)
- No separate API key — uses our existing AWS OIDC auth
- Already in our account (496411573616, us-west-2)
- R1 for reasoning, V3 for general tasks
- We're broke but this is affordable enough to build with

Available models on Bedrock:
- deepseek-r1    → reasoning (math, logic, complex decisions)
- deepseek-v3.1  → general purpose (classification, summarization, plans)

Auth: IAM role via OIDC (GitHub Actions / ECS task role). Zero stored creds.
"""

import json
import os
from typing import Optional

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


class BedrockDeepSeek:
    """
    DeepSeek through AWS Bedrock. Cheap. No separate API key.
    This is our primary AI model for everything.
    """

    REGION = os.environ.get("AWS_REGION", "us-west-2")

    # DeepSeek models on Bedrock
    MODELS = {
        "fast": "deepseek.deepseek-v3-1-v1:0",      # General — cheap, fast
        "reason": "deepseek.deepseek-r1-v1:0",       # Reasoning — for hard problems
    }

    def __init__(self, region: Optional[str] = None):
        self.region = region or self.REGION
        self._runtime = None

    @property
    def runtime(self):
        if self._runtime is None:
            if not HAS_BOTO3:
                raise RuntimeError("boto3 not installed. Run: pip install boto3")
            self._runtime = boto3.client(
                "bedrock-runtime",
                config=Config(
                    region_name=self.region,
                    retries={"max_attempts": 3, "mode": "adaptive"},
                ),
            )
        return self._runtime

    def ask(self, prompt: str, system: str = "", use_reasoning: bool = False, max_tokens: int = 1024) -> str:
        """
        Ask DeepSeek something via Bedrock. Returns text.
        
        use_reasoning=True → uses R1 (slower, smarter, costs more tokens)
        use_reasoning=False → uses V3 (fast, cheap, good enough for most things)
        """
        model_id = self.MODELS["reason"] if use_reasoning else self.MODELS["fast"]

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        })

        try:
            response = self.runtime.invoke_model(
                modelId=model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            # Bedrock DeepSeek returns OpenAI-compatible format
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            # Fallback: some versions return differently
            return result.get("content", result.get("output", str(result)))

        except Exception as e:
            error_msg = str(e)
            if "AccessDeniedException" in error_msg:
                return "[ERROR: No access to DeepSeek on Bedrock. Enable model access in AWS console.]"
            elif "ResourceNotFoundException" in error_msg:
                return "[ERROR: DeepSeek model not found. Check region and model ID.]"
            elif "ThrottlingException" in error_msg:
                return "[ERROR: Throttled. Wait and retry.]"
            return f"[ERROR: {error_msg}]"

    def classify_repo(self, repo: dict) -> dict:
        """Classify a repo into category + action. Cheap call."""
        prompt = f"""Classify this GitHub repo. Short answers.

Name: {repo.get('name', '')}
Description: {repo.get('description', 'none')}  
Language: {repo.get('language', 'unknown')}
Has code: {repo.get('has_real_code', False)}
Health: {repo.get('health_score', 0)}
Archived: {repo.get('archived', False)}

Categories: infrastructure, product, intelligence, agent, data, governance, vertical, research, delivery, ops
Actions: KEEP, MERGE, REBUILD, ARCHIVE, DELETE

JSON only: {{"category": "...", "action": "...", "reason": "..."}}"""

        result = self.ask(prompt, system="Classify repos. JSON only. No markdown fences.")

        try:
            text = result.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if text.startswith("{"):
                return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            pass

        return {"category": "unknown", "action": "KEEP", "reason": "parse failed"}

    def batch_classify(self, repos: list[dict], batch_size: int = 10) -> list[dict]:
        """
        Classify repos in batches to save tokens.
        Sends multiple repos in one prompt.
        """
        results = []

        for i in range(0, len(repos), batch_size):
            batch = repos[i:i + batch_size]

            repo_list = "\n".join([
                f"{j+1}. {r['name']} | lang:{r.get('language', '?')} | "
                f"health:{r.get('health_score', 0)} | archived:{r.get('archived', False)} | "
                f"code:{r.get('has_real_code', False)} | desc:{r.get('description', 'none')[:60]}"
                for j, r in enumerate(batch)
            ])

            prompt = f"""Classify these {len(batch)} repos. JSON array only.

{repo_list}

Categories: infrastructure, product, intelligence, agent, data, governance, vertical, research, delivery, ops
Actions: KEEP, MERGE, REBUILD, ARCHIVE, DELETE

Reply as JSON array: [{{"name": "...", "category": "...", "action": "...", "reason": "..."}}]"""

            result = self.ask(prompt, system="Classify repos. JSON array only. No explanation.")

            try:
                text = result.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    results.extend(parsed)
                    continue
            except (json.JSONDecodeError, IndexError):
                pass

            # Fallback: classify one by one
            for repo in batch:
                results.append(self.classify_repo(repo))

        return results

    def summarize(self, text: str, max_words: int = 50) -> str:
        """Summarize text. Short and cheap."""
        if not text or len(text) < 50:
            return text
        return self.ask(
            f"Summarize in {max_words} words max:\n\n{text[:2000]}",
            system="Summarize. Be brief."
        )

    def generate_rebuild_plan(self, ontology_summary: str) -> str:
        """
        Generate rebuild plan. Uses V3 (not R1) — good enough and cheaper.
        """
        return self.ask(
            f"""You are Shafanna, master agent for Maroon Technologies.
Generate a practical rebuild plan from this ontology data.

Rules:
- We're broke. Free tier everything possible.
- Be specific: which repos to delete, merge, rebuild.
- Phase it: cleanup first, then foundation, then products.
- Keep it real. No fluff.

Ontology data:
{ontology_summary[:3000]}""",
            system="You are Shafanna. Generate actionable rebuild plans. Be direct. No fluff.",
            max_tokens=2048,
        )

    def is_available(self) -> bool:
        """Check if Bedrock DeepSeek is reachable."""
        if not HAS_BOTO3:
            return False
        try:
            # Tiny test call
            self.ask("Say 'ok'", max_tokens=5)
            return True
        except Exception:
            return False
