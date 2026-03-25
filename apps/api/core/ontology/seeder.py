DEFAULT_RELATIONSHIPS = [
    ("India", "China", "NEIGHBOR_OF"),
    ("India", "Pakistan", "NEIGHBOR_OF"),
    ("India", "Bangladesh", "NEIGHBOR_OF"),
    ("India", "United States", "STRATEGIC_PARTNER"),
    ("India", "Russia", "DEFENSE_PARTNER"),
    ("India", "Indian Ocean", "OPERATES_IN"),
]


async def seed_countries(driver, countries: list[str]):
    async with driver.session() as session:
        for country in countries:
            await session.run(
                """
                MERGE (n:Nation {name: $name})
                SET n.color = "#4E8C7A", n.updated_at = datetime()
                """,
                name=country,
            )


async def seed_relationships(driver, relationships: list[tuple[str, str, str]] | None = None):
    relationships = relationships or DEFAULT_RELATIONSHIPS
    async with driver.session() as session:
        for source, target, relation in relationships:
            await session.run(
                f"""
                MERGE (a:Entity {{name: $source}})
                MERGE (b:Entity {{name: $target}})
                MERGE (a)-[r:{relation}]->(b)
                SET r.updated_at = datetime(), r.strength_score = 0.8
                """,
                source=source,
                target=target,
            )
