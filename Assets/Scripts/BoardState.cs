using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using UnityEngine;

// Board state for the digital game board (design doc Section 4.2, Bailey's Sprint 2 story).
//
// Kade's receiver parses and validates the CV data, then hands the ACCEPTED board
// to this script with SubmitAcceptedBoard(). This script keeps the digital board
// matching it: tiles are added, moved, rotated, or removed.
//
// - Tiles are tracked by their unique ArUco ID (Section 3.7), so a moved tile keeps
//   the same GameObject instead of being destroyed and re-created.
// - Kade's receiver does the real validation (duplicates, stale messages, temporary
//   marker loss). This script only skips data it cannot place, with a warning.
// - ID 0 is the CV system's board-orientation reference marker and is never placed.
// - Grid coordinates use a bottom-left origin (0,0), X right and Y up (requirements RF14).
// - Tiles are only created and moved on Unity's main thread, in Update().
public class BoardState : MonoBehaviour
{
    // One accepted tile, as supplied by the receiving component.
    [Serializable]
    public struct TileData
    {
        public int id;
        public int x;           // column, 0 = left
        public int y;           // row, 0 = bottom
        public int orientation; // rotation steps (see Degrees Per Step)

        public TileData(int id, int x, int y, int orientation)
        {
            this.id = id;
            this.x = x;
            this.y = y;
            this.orientation = orientation;
        }
    }

    [Serializable]
    public class TilePrefab
    {
        public int id;
        public GameObject prefab;
    }

    class PlacedTile
    {
        public int id;
        public Vector2Int cell;
        public int orientation;
        public GameObject obj;
    }

    // CV-format JSON, used only by the testing helpers below.
    [Serializable] class CvHex { public int id; public int x; public int y; public int width; public int height; public int orientation; }
    [Serializable] class CvBoard { public int hex_count; public CvHex[] hexes; }

    [Header("References")]
    public WebcamGrid grid;

    [Header("Tile prefabs")]
    [Tooltip("Used when a tile ID has no entry in the list below.")]
    public GameObject defaultTilePrefab;
    public TilePrefab[] tilePrefabs;

    [Header("Empty cells")]
    [Tooltip("Background object placed in every cell that has no tile. Any 2D colliders on it are removed so it never blocks the laser.")]
    public GameObject emptyTilePrefab;
    [Tooltip("Sorting order for empty-cell sprites, so they draw behind tiles and the laser.")]
    public int emptySortingOrder = -10;

    [Header("Reference marker")]
    [Tooltip("ArUco ID the CV system uses to orient the board. It is never placed as a tile.")]
    public int referenceMarkerId = 0;

    [Header("Orientation")]
    [Tooltip("Degrees per orientation step (0, 1, 2, 3).")]
    public float degreesPerStep = 90f;
    [Tooltip("Rotate clockwise as the orientation value increases.")]
    public bool clockwise = true;

    [Header("Testing")]
    [Tooltip("Optional CV-format board JSON loaded on Start, for testing without the camera.")]
    public TextAsset sampleBoard;

    readonly ConcurrentQueue<TileData[]> pending = new ConcurrentQueue<TileData[]>();
    readonly Dictionary<int, PlacedTile> tilesById = new Dictionary<int, PlacedTile>();
    readonly Dictionary<Vector2Int, int> idByCell = new Dictionary<Vector2Int, int>();
    readonly Dictionary<int, GameObject> prefabLookup = new Dictionary<int, GameObject>();
    readonly Dictionary<Vector2Int, GameObject> emptyTiles = new Dictionary<Vector2Int, GameObject>();
    Transform emptyParent;
    int emptyColumns, emptyRows;

    public int TileCount => tilesById.Count;

    void Awake()
    {
        if (tilePrefabs == null) return;
        foreach (TilePrefab entry in tilePrefabs)
            if (entry != null && entry.prefab != null)
                prefabLookup[entry.id] = entry.prefab;
    }

    void Start()
    {
        if (grid == null)
        {
            Debug.LogError("BoardState needs a WebcamGrid reference.");
            enabled = false;
            return;
        }
        if (defaultTilePrefab == null)
            Debug.LogWarning("BoardState has no Default Tile Prefab; unmapped tiles will be invisible.");
        RefreshEmptyTiles();
        if (sampleBoard != null) SubmitJson(sampleBoard.text);
    }

    // ---- Input from Kade's receiver ---------------------------------------

    // Hand over the full accepted board. Safe to call from any thread.
    public void SubmitAcceptedBoard(TileData[] tiles)
    {
        if (tiles == null) return;
        pending.Enqueue((TileData[])tiles.Clone());
    }

    // ---- Testing helper ---------------------------------------------------

    // Converts CV-format JSON ({"hex_count", "hexes": [...]}) and submits it.
    // For testing only; in the game, Kade's receiver calls SubmitAcceptedBoard().
    public void SubmitJson(string json)
    {
        CvBoard board;
        try
        {
            board = JsonUtility.FromJson<CvBoard>(json);
        }
        catch (Exception e)
        {
            Debug.LogWarning($"Test JSON rejected: invalid JSON ({e.Message})");
            return;
        }
        if (board == null || board.hexes == null)
        {
            Debug.LogWarning("Test JSON rejected: no \"hexes\" array.");
            return;
        }
        if (board.hex_count != board.hexes.Length)
            Debug.LogWarning($"hex_count is {board.hex_count}, but {board.hexes.Length} tiles were sent.");

        var tiles = new List<TileData>();
        foreach (CvHex hex in board.hexes)
            if (hex != null) tiles.Add(new TileData(hex.id, hex.x, hex.y, hex.orientation));
        SubmitAcceptedBoard(tiles.ToArray());
    }

    // ---- Applying updates (main thread) -----------------------------------

    void Update()
    {
        // Only the newest board matters, so skip any older ones.
        TileData[] latest = null;
        while (pending.TryDequeue(out TileData[] tiles)) latest = tiles;
        if (latest != null) ApplyAcceptedBoard(latest);
    }

    void ApplyAcceptedBoard(TileData[] tiles)
    {
        // Collect the tiles that can be placed.
        var incoming = new Dictionary<int, TileData>();
        var claimedCells = new HashSet<Vector2Int>();
        foreach (TileData tile in tiles)
        {
            if (tile.id == referenceMarkerId) continue;
            if (incoming.ContainsKey(tile.id))
            {
                Debug.LogWarning($"Tile skipped: ID {tile.id} appears more than once.");
                continue;
            }
            if (!grid.TryCellToWorld(tile.x, tile.y, out _))
            {
                Debug.LogWarning($"Tile skipped: ID {tile.id} at ({tile.x}, {tile.y}) is off the {grid.columns}x{grid.rows} board.");
                continue;
            }
            if (!claimedCells.Add(new Vector2Int(tile.x, tile.y)))
            {
                Debug.LogWarning($"Tile skipped: ID {tile.id} would overlap another tile in cell ({tile.x}, {tile.y}).");
                continue;
            }
            incoming[tile.id] = tile;
        }

        int added = 0, removed = 0, moved = 0, rotated = 0;

        // Remove tiles that are no longer on the board.
        var gone = new List<int>();
        foreach (int id in tilesById.Keys)
            if (!incoming.ContainsKey(id)) gone.Add(id);
        foreach (int id in gone)
        {
            Destroy(tilesById[id].obj);
            tilesById.Remove(id);
            removed++;
        }

        // Move, rotate, or add the rest.
        foreach (TileData tile in incoming.Values)
        {
            var cell = new Vector2Int(tile.x, tile.y);
            if (tilesById.TryGetValue(tile.id, out PlacedTile placed))
            {
                if (placed.cell != cell)
                {
                    grid.TryCellToWorld(cell.x, cell.y, out Vector3 position);
                    placed.obj.transform.position = position;
                    placed.cell = cell;
                    placed.obj.name = TileName(tile.id, cell);
                    moved++;
                }
                if (placed.orientation != tile.orientation)
                {
                    placed.orientation = tile.orientation;
                    placed.obj.transform.rotation = OrientationToRotation(tile.orientation);
                    rotated++;
                }
            }
            else
            {
                tilesById[tile.id] = Spawn(tile);
                added++;
            }
        }

        idByCell.Clear();
        foreach (PlacedTile placed in tilesById.Values)
            idByCell[placed.cell] = placed.id;
        RefreshEmptyTiles();

        if (added + removed + moved + rotated > 0)
            Debug.Log($"Board updated: {added} added, {removed} removed, {moved} moved, " +
                      $"{rotated} rotated ({tilesById.Count} tiles on board).");
    }

    // ---- Queries for other scripts (e.g. the laser) ------------------------

    public bool TryGetTile(int column, int row, out int id, out int orientation)
    {
        if (idByCell.TryGetValue(new Vector2Int(column, row), out id))
        {
            orientation = tilesById[id].orientation;
            return true;
        }
        id = -1;
        orientation = -1;
        return false;
    }

    public bool TryGetTileCell(int id, out Vector2Int cell)
    {
        if (tilesById.TryGetValue(id, out PlacedTile placed))
        {
            cell = placed.cell;
            return true;
        }
        cell = new Vector2Int(-1, -1);
        return false;
    }

    // ---- Helpers -------------------------------------------------------------

    PlacedTile Spawn(TileData tile)
    {
        var cell = new Vector2Int(tile.x, tile.y);
        grid.TryCellToWorld(cell.x, cell.y, out Vector3 position);
        Quaternion rotation = OrientationToRotation(tile.orientation);
        GameObject prefab = prefabLookup.TryGetValue(tile.id, out GameObject mapped) ? mapped : defaultTilePrefab;

        GameObject obj;
        if (prefab != null)
        {
            obj = Instantiate(prefab, position, rotation, transform);
        }
        else
        {
            obj = new GameObject();
            obj.transform.SetParent(transform, false);
            obj.transform.SetPositionAndRotation(position, rotation);
        }
        obj.name = TileName(tile.id, cell);
        return new PlacedTile { id = tile.id, cell = cell, orientation = tile.orientation, obj = obj };
    }

    static string TileName(int id, Vector2Int cell) => $"Tile {id} ({cell.x}, {cell.y})";

    // Shows an empty-cell object in every cell without a tile, and hides it where a tile sits.
    void RefreshEmptyTiles()
    {
        if (emptyTilePrefab == null) return;
        if (emptyColumns != grid.columns || emptyRows != grid.rows) BuildEmptyTiles();
        foreach (KeyValuePair<Vector2Int, GameObject> pair in emptyTiles)
            if (pair.Value != null) pair.Value.SetActive(!idByCell.ContainsKey(pair.Key));
    }

    void BuildEmptyTiles()
    {
        foreach (GameObject obj in emptyTiles.Values)
            if (obj != null) Destroy(obj);
        emptyTiles.Clear();

        if (emptyParent == null)
        {
            emptyParent = new GameObject("EmptyCells").transform;
            emptyParent.SetParent(transform, false);
        }

        emptyColumns = grid.columns;
        emptyRows = grid.rows;
        for (int row = 0; row < emptyRows; row++)
        {
            for (int column = 0; column < emptyColumns; column++)
            {
                if (!grid.TryCellToWorld(column, row, out Vector3 position)) continue;
                GameObject obj = Instantiate(emptyTilePrefab, position, Quaternion.identity, emptyParent);
                obj.name = $"Empty ({column}, {row})";
                foreach (Collider2D col in obj.GetComponentsInChildren<Collider2D>())
                    Destroy(col);
                foreach (SpriteRenderer sprite in obj.GetComponentsInChildren<SpriteRenderer>())
                    sprite.sortingOrder = emptySortingOrder;
                emptyTiles[new Vector2Int(column, row)] = obj;
            }
        }
    }

    Quaternion OrientationToRotation(int orientation)
    {
        float angle = orientation * degreesPerStep * (clockwise ? -1f : 1f);
        return Quaternion.Euler(0f, 0f, angle);
    }
}
