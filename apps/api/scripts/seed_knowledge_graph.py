import asyncio

from neo4j import AsyncGraphDatabase

from config import settings
from core.ontology.seeder import seed_relationships


async def main():
    driver = AsyncGraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
    try:
        await seed_relationships(driver)
        print("Seeded base strategic relationships into Neo4j")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
