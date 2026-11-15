from types import SimpleNamespace as NS

from portfolio_agent.agent import PortfolioAgent


class FakeToolbox:
    def execute(self, name, args):
        return '{"total_value": 2500}', False


class FakeClient:
    """Risponde prima con una chiamata a uno strumento, poi con il testo finale."""

    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kwargs):
        self.calls.append([dict(m) for m in kwargs["messages"]])
        if len(self.calls) == 1:
            block = NS(type="tool_use", id="tu_1", name="get_portfolio", input={})
            return NS(stop_reason="tool_use", content=[block])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Mantieni.")])


def test_tool_loop_feeds_results_back():
    client, seen = FakeClient(), []
    agent = PortfolioAgent(FakeToolbox(), client=client, on_tool=lambda n, a: seen.append(n))
    assert agent.ask("Come va?") == "Mantieni."
    assert seen == ["get_portfolio"]
    result = client.calls[1][-1]["content"][0]
    assert result["tool_use_id"] == "tu_1" and result["is_error"] is False
    assert [m["role"] for m in agent.messages] == ["user", "assistant", "user", "assistant"]
