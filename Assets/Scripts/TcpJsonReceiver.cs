using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

public class TcpJsonReceiver : MonoBehaviour
{
    [SerializeField] private int port = 5005;
    [SerializeField] private int boardWidth = 6;
    [SerializeField] private int boardHeight = 6;

    private TcpListener tcpListener;
    private Thread listenerThread;
    private volatile bool isRunning;

    private readonly ConcurrentQueue<string> receivedMessages =
        new ConcurrentQueue<string>();

    private readonly ConcurrentQueue<string> statusMessages =
        new ConcurrentQueue<string>();

    private void Start()
    {
        StartListener();
    }

    private void Update()
    {
        // Display connection messages safely on Unity's main thread.
        while (statusMessages.TryDequeue(out string status))
        {
            Debug.Log(status);
        }

        // Process received JSON safely on Unity's main thread.
        while (receivedMessages.TryDequeue(out string json))
        {
            ParseAndValidate(json);
        }
    }

    private void StartListener()
    {
        if (isRunning)
        {
            return;
        }

        isRunning = true;

        listenerThread = new Thread(ListenForConnections);
        listenerThread.IsBackground = true;
        listenerThread.Start();

        Debug.Log($"Starting TCP listener on port {port}...");
    }

    private void ListenForConnections()
    {
        try
        {
            tcpListener = new TcpListener(IPAddress.Loopback, port);
            tcpListener.Start();

            statusMessages.Enqueue(
                $"Unity is listening on 127.0.0.1:{port}"
            );

            while (isRunning)
            {
                TcpClient client = tcpListener.AcceptTcpClient();

                statusMessages.Enqueue("Python sender connected.");

                HandleClient(client);
            }
        }
        catch (SocketException exception)
        {
            if (isRunning)
            {
                statusMessages.Enqueue(
                    $"TCP error: {exception.Message}"
                );
            }
        }
        catch (Exception exception)
        {
            if (isRunning)
            {
                statusMessages.Enqueue(
                    $"Listener error: {exception.Message}"
                );
            }
        }
    }

    private void HandleClient(TcpClient client)
    {
        try
        {
            using (client)
            using (NetworkStream stream = client.GetStream())
            using (StreamReader reader = new StreamReader(stream))
            {
                while (isRunning)
                {
                    // Joseph's sender places one JSON object on each line.
                    string line = reader.ReadLine();

                    if (line == null)
                    {
                        break;
                    }

                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        receivedMessages.Enqueue(line);
                    }
                }
            }
        }
        catch (IOException exception)
        {
            statusMessages.Enqueue(
                $"Connection ended: {exception.Message}"
            );
        }
        finally
        {
            statusMessages.Enqueue("Python sender disconnected.");
        }
    }


    private void ParseAndValidate(string json)
    {
        TileMessage message;

        try
        {
            message = JsonUtility.FromJson<TileMessage>(json);
        }
        catch (Exception exception)
        {
            Debug.LogWarning($"Invalid JSON: {exception.Message}");
            return;
        }

        if (message == null || message.tiles == null)
        {
            Debug.LogWarning("Invalid message: missing tiles array.");
            return;
        }

        Debug.Log($"Received {message.tile} tiles.");

        foreach (TileData tile in message.tiles)
        {
            if (tile == null)
                continue;

            //if (tile.x_coord < 0 || tile.x_coord >= boardWidth)
            //{
            //    Debug.LogWarning(
            //        $"Tile {tile.id} rejected: X coordinate out of range."
            //    );
            //    continue;
            //}

            //if (tile.y_coord < 0 || tile.y_coord >= boardHeight)
            //{
            //    Debug.LogWarning(
            //        $"Tile {tile.id} rejected: Y coordinate out of range."
            //    );
            //    continue;
            //}

            float normalizedRotation = NormalizeRotation(tile.orientation);

            Debug.Log(
                $"Tile accepted — ID: {tile.id}, " +
                $"Position: ({tile.x_coord}, {tile.y_coord}), " +
                $"Rotation: {normalizedRotation}°"
            );
        }
    }



    private bool ValidateTile(
        TileData tile,
        out string rejectionReason
    )
    {
        if (tile == null)
        {
            rejectionReason = "Tile data is missing.";
            return false;
        }

        if (tile.id < 0)
        {
            rejectionReason = "Tile ID cannot be negative.";
            return false;
        }

        if (tile.x_coord < 0 || tile.x_coord >= boardWidth)
        {
            rejectionReason =
                $"X must be between 0 and {boardWidth - 1}.";
            return false;
        }

        if (tile.y_coord < 0 || tile.y_coord >= boardHeight)
        {
            rejectionReason =
                $"Y must be between 0 and {boardHeight - 1}.";
            return false;
        }

        rejectionReason = "";
        return true;
    }


    private float NormalizeRotation(float rotation)
    {
        rotation = (rotation % 360f + 360f) % 360f;

        float normalized =
            Mathf.Round(rotation / 90f) * 90f;

        return normalized % 360f;
    }

    private void OnApplicationQuit()
    {
        StopListener();
    }

    private void OnDestroy()
    {
        StopListener();
    }

    private void StopListener()
    {
        if (!isRunning)
        {
            return;
        }

        isRunning = false;

        if (tcpListener != null)
        {
            tcpListener.Stop();
            tcpListener = null;
        }

        if (listenerThread != null &&
            listenerThread.IsAlive)
        {
            listenerThread.Join(1000);
        }

        listenerThread = null;
    }
}