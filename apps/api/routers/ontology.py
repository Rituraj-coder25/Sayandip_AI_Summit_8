from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/graph")
async def get_graph(request: Request, entity: str = "India", depth: int = 2):
    from ..core.ontology.graph_engine import OntologyGraphEngine

    graph = OntologyGraphEngine(request.app.state.neo4j)
    return await graph.get_entity_neighborhood(entity, depth=depth)


@router.get("/connect")
async def find_connection(request: Request, entity_a: str, entity_b: str):
    from ..core.ontology.graph_engine import OntologyGraphEngine

    graph = OntologyGraphEngine(request.app.state.neo4j)
    paths = await graph.find_all_paths(entity_a, entity_b, max_hops=6)
    if not paths:
        return {"found": False, "message": f"No connection found between {entity_a} and {entity_b} within 6 degrees."}

    path_desc = "\n".join(
        [
            f"Path {index + 1} ({path['hops']} hops): "
            + " -> ".join(
                f"{path['nodes'][node_index]} [{path['rels'][node_index]}] {path['nodes'][node_index + 1]}"
                for node_index in range(len(path["rels"]))
            )
            for index, path in enumerate(paths)
        ]
    )
    explanation = await request.app.state.analyst.query(
        question=(
            f"Explain the strategic connection between {entity_a} and {entity_b} for India's decision-makers.\n\n"
            f"Knowledge graph paths found:\n{path_desc}"
        ),
        user_role="ANALYST",
        conversation_history=[],
    )
    return {"found": True, "paths": paths, "explanation": explanation.get("response", "")}