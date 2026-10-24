from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dice")

@mcp.tool()
def roll(sides: int = 6) -> int:
    """Roll one die with the given number of sides and return the result."""
    import random
    return random.randint(1, sides)

if __name__ == "__main__":
    mcp.run()  # stdio by default