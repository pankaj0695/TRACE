from langgraph.graph import END, START, StateGraph

from app.agents.anomaly import AnomalyAgent
from app.agents.authenticity import AuthenticityAgent
from app.agents.ingestion import IngestionAgent
from app.agents.investigator import InvestigatorAgent
from app.agents.network import NetworkAgent
from app.agents.orchestrator import DETECTORS, OrchestratorAgent
from app.agents.scoring import TrustScoringAgent
from app.pipeline.state import PipelineState

# Stage order exposed to clients so they can render the pipeline before it runs.
STAGES = ["ingestion", *DETECTORS, "scoring", "investigator", "orchestrator"]


def build_pipeline(
    ingestion: IngestionAgent,
    anomaly: AnomalyAgent,
    authenticity: AuthenticityAgent,
    network: NetworkAgent,
    scoring: TrustScoringAgent,
    orchestrator: OrchestratorAgent,
    investigator: InvestigatorAgent | None = None,
):
    """ingestion -> (anomaly | authenticity | network) in parallel -> scoring -> [escalation check]
    -> investigator -> scoring (bounded rounds) | orchestrator report."""
    g = StateGraph(PipelineState)
    for agent in (ingestion, anomaly, authenticity, network, scoring):
        g.add_node(agent.name, agent)
    g.add_node(orchestrator.name, orchestrator)

    g.add_edge(START, ingestion.name)
    g.add_conditional_edges(ingestion.name, orchestrator.route, [*DETECTORS, scoring.name])
    for detector in DETECTORS:
        g.add_edge(detector, scoring.name)
    if investigator is None:
        g.add_edge(scoring.name, orchestrator.name)
    else:
        g.add_node(investigator.name, investigator)
        g.add_conditional_edges(
            scoring.name,
            lambda s: investigator.name if investigator.should_escalate(s) else orchestrator.name,
            {investigator.name: investigator.name, orchestrator.name: orchestrator.name},
        )
        g.add_edge(investigator.name, scoring.name)
    g.add_edge(orchestrator.name, END)
    return g.compile()
