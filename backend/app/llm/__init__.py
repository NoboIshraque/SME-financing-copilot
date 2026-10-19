"""LLM gateway (WP-10): the only way Hishab talks to a language model.

    from app.llm import LLMGateway, LLMRequest, Message, Role, Task
    gateway = LLMGateway(settings)
    reply = gateway.complete(LLMRequest(Role.brain, Task.plan, messages, context={...}))
"""

from app.llm.gateway import LLMGateway, NoProviderAvailable, parse_json_object, prepare_messages
from app.llm.messages import Attempt, LLMRequest, LLMResponse, Message, Outcome, Task
from app.llm.providers import PROVIDERS, Provider, Role, chain

__all__ = ["PROVIDERS", "Attempt", "LLMGateway", "LLMRequest", "LLMResponse", "Message",
           "NoProviderAvailable", "Outcome", "Provider", "Role", "Task", "chain",
           "parse_json_object", "prepare_messages"]
