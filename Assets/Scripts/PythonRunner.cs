using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;

public class PythonRunner : MonoBehaviour
{
    public string pythonExecutablePath =
        @"C:\Users\Joseph\Documents\CV Board Project Files\CVBoard-2026-10-14-15-18-49\Assets\Scripts\.venv\Scripts\python.exe";

    private async void Start()
    {
        string scriptPath = Path.Combine(
            Application.dataPath,
            "Scripts",
            "tile_detection.py"
        );

        try
        {
            await RunPythonScriptAsync(scriptPath);
        }
        catch (Exception e)
        {
            UnityEngine.Debug.LogError(
                "Failed to run Python: " + e.Message
            );
        }
    }

    public async Task RunPythonScriptAsync(string path)
    {
        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = pythonExecutablePath,
            Arguments = "\"" + path + "\"",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        using (Process process = new Process())
        {
            process.StartInfo = startInfo;

            process.Start();

            // Read both streams concurrently to avoid pipe deadlocks.
            Task<string> outputTask =
                process.StandardOutput.ReadToEndAsync();

            Task<string> errorTask =
                process.StandardError.ReadToEndAsync();

            // Asynchronously wait for output streams to close.
            await Task.WhenAll(outputTask, errorTask);

            string output = await outputTask;
            string errors = await errorTask;

            if (!string.IsNullOrEmpty(output))
            {
                UnityEngine.Debug.Log("Python Output: " + output);
            }

            if (!string.IsNullOrEmpty(errors))
            {
                UnityEngine.Debug.LogError("Python Error: " + errors);
            }

            if (process.ExitCode != 0)
            {
                UnityEngine.Debug.LogError(
                    "Python exited with code: " + process.ExitCode
                );
            }
        }
    }
}
