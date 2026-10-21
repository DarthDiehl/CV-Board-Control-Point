using System.Threading.Tasks;
using UnityEngine;

// Test helper: sends board JSON files to BoardState one at a time, so it can be
// checked without the camera or the TCP receiver. Not needed in the final game.
public class BoardStateTester : MonoBehaviour
{
    public BoardState board;
    [Tooltip("Board JSON files to send, in order.")]
    public TextAsset[] steps;
    [Tooltip("Send from a background thread, the way the TCP receiver will.")]
    public bool sendFromBackgroundThread;

    int next;

    void OnGUI()
    {
        if (board == null || steps == null || steps.Length == 0) return;

        string nextName = next >= steps.Length ? "all steps sent"
                        : steps[next] != null ? steps[next].name : "(empty slot)";

        GUILayout.BeginArea(new Rect(10, 70, 380, 130), GUI.skin.box);
        GUILayout.Label($"Board test: {next}/{steps.Length} sent | next: {nextName}");
        GUILayout.Label($"Tiles on board: {board.TileCount}");
        GUILayout.BeginHorizontal();
        GUI.enabled = next < steps.Length;
        if (GUILayout.Button("Send next")) SendNext();
        GUI.enabled = true;
        if (GUILayout.Button("Restart")) next = 0;
        GUILayout.EndHorizontal();
        sendFromBackgroundThread = GUILayout.Toggle(sendFromBackgroundThread, "Send from background thread");
        GUILayout.EndArea();
    }

    void SendNext()
    {
        TextAsset step = steps[next++];
        if (step == null) return;
        string json = step.text;
        Debug.Log($"[Test] Sending {step.name}");
        if (sendFromBackgroundThread)
            Task.Run(() => board.SubmitJson(json));
        else
            board.SubmitJson(json);
    }
}
