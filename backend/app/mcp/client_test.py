
import asyncio

# Importer le client MCP et son transport HTTP
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    # Se connecter au serveur MCP
    async with streamable_http_client(
        "http://localhost:8001/mcp"
    ) as (read_stream, write_stream):

        # Créer une session avec le serveur
        async with ClientSession(read_stream, write_stream) as session:

            # Initialiser la communication
            await session.initialize()

            # Récupérer les outils disponibles
            tools = await session.list_tools()

            # Afficher leurs noms
            print("Outils MCP disponibles :")
            for tool in tools.tools:
                print("-", tool.name)


# Lancer le programme
if __name__ == "__main__":
    asyncio.run(main())
