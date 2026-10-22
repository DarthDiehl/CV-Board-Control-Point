
using System;
using UnityEngine;

[Serializable]
public class TileMessage
{
    public int tile;
    public TileData[] tiles;
}

[Serializable]
public class TileData
{
    public int id;
    public int x_pos;
    public int y_pos;
    public int width;
    public int height;
    public int orientation;
    public int x_coord;
    public int y_coord;
}
