import json
import math
import numpy as np
import cv2
import cv2.aruco as aruco
from tcp_sender import JsonTcpSender

tile_marker_ratio = 1 / 1

sender = JsonTcpSender("127.0.0.1", 5005)
sender.start()


def convert_pos_coords(tiles: list):
    """Manipulates the list, tiles, to add the x and y coordinate values so that the tiles can be easily mapped to a grid."""

    # empty case
    if len(tiles) == 0:
        return np.zeros((0, 0), dtype=int)

    width_median = np.median(np.array([tile["width"] for tile in tiles]))
    width_tolerance = width_median * 0.2

    tiles = sorted(tiles, key=lambda tile: tile["x_pos"])

    # Bin similar x values
    x_bins = []

    for tile in tiles:
        x_pos = tile["x_pos"]

        # Create first bin
        if len(x_bins) == 0:
            x_bins.append([x_pos])
        elif abs(x_pos - np.mean(x_bins[-1])) < width_tolerance:
            x_bins[-1].append(x_pos)
        else:
            x_bins.append([x_pos])

    # Calculate the average position of each group
    x_bin_means = [np.mean(group) for group in x_bins]

    # Map actual X positions to grid coordinates
    x_pos_coords = {}

    for i, bin in enumerate(x_bins):
        if i == 0:
            coord = 0
        else:
            # Sets the coord to be the previous groups coord + the number of tile widths apart from the previous group
            mean_distance = x_bin_means[i] - x_bin_means[i - 1]
            coord = round(mean_distance / width_median) + x_pos_coords[x_bins[i - 1][0]]

        for x_pos in bin:
            x_pos_coords[x_pos] = coord

    # Repeat the same steps with y values
    height_median = np.median(np.array([tile["height"] for tile in tiles]))
    height_tolerance = height_median * 0.2

    tiles = sorted(tiles, key=lambda tile: tile["y_pos"])

    # Bin similar y values
    y_bins = []

    for tile in tiles:
        y_pos = tile["y_pos"]

        # Create first bin
        if len(y_bins) == 0:
            y_bins.append([y_pos])
        elif abs(y_pos - np.mean(y_bins[-1])) < height_tolerance:
            y_bins[-1].append(y_pos)
        else:
            y_bins.append([y_pos])

    # Calculate the average position of each group
    y_bin_means = [np.mean(group) for group in y_bins]

    # Map actual y positions to grid coordinates
    y_pos_coords = {}

    for i, bin in enumerate(y_bins):
        if i == 0:
            coord = 0
        else:
            # Sets the coord to be the previous groups coord + the number of tile widths apart from the previous group
            mean_distance = y_bin_means[i] - y_bin_means[i - 1]
            coord = (
                round(mean_distance / height_median) + y_pos_coords[y_bins[i - 1][0]]
            )

        for y_pos in bin:
            y_pos_coords[y_pos] = coord

    for tile in tiles:
        x_pos = tile["x_pos"]
        y_pos = tile["y_pos"]
        tile["x_coord"] = x_pos_coords[x_pos]
        tile["y_coord"] = y_pos_coords[y_pos]


def board_matrix(tiles: list):
    """Returns a 2D matrix represntation of the board for quick positional error checking.
    Should be used after tiles has already been passed through convert_pos_coords().
    """
    # null case
    if len(tiles) == 0:
        return ""

    x_max = max(tiles, key=lambda tile: tile["x_coord"])["x_coord"]
    y_max = max(tiles, key=lambda tile: tile["y_coord"])["y_coord"]

    board_matrix = np.full((y_max + 1, x_max + 1), " ")

    for tile in tiles:
        board_matrix[tile["y_coord"]][tile["x_coord"]] = tile["id"]

    return board_matrix


# 1. Load your camera calibration data (Required for accurate 3D orientation)
camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=float)
dist_coeffs = np.zeros((5, 1))

# Define physical marker size in meters (e.g., 0.05 = 5cm)
MARKER_SIZE = 0.05

# 2. Initialize video capture and ArUco parameters

# CAMERA INDEX
# CAMERA INDEX
# CAMERA INDEX
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
# CAMERA INDEX
# CAMERA INDEX
# CAMERA INDEX

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Match this to the dictionary you selected online
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_ARUCO_ORIGINAL)
parameters = aruco.DetectorParameters()
detector = aruco.ArucoDetector(aruco_dict, parameters)

if not cap.isOpened():
    print("Could not open camera")
    exit()


# camera loop
while True:

    ret, frame = cap.read()

    if not ret:
        print("Could not read frame")
        continue

    # Convert frame to grayscale for optimal marker detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Detect markers
    corners, ids, rejected = detector.detectMarkers(gray)

    tiles = []

    if ids is not None:
        # Flatten IDs array
        ids = ids.flatten()

        # parses info from every marker detected
        for corners, id in zip(corners, ids):
            pts = corners.reshape((4, 2))
            topLeft, topRight, bottomRight, bottomLeft = pts
            x = int((topLeft[0] + bottomRight[0]) / 2.0)
            y = int((topLeft[1] + bottomRight[1]) / 2.0)
            marker_width = int(cv2.norm(topRight - topLeft))
            marker_height = int(cv2.norm(bottomLeft - topLeft))
            width = int(marker_width * tile_marker_ratio)
            height = int(marker_height * tile_marker_ratio)
            dx = topRight[0] - topLeft[0]
            dy = topRight[1] - topLeft[1]
            orientation = math.degrees(math.atan2(dy, dx)) % 360

            tile_info = {
                "id": int(id),
                "x_pos": x,
                "y_pos": y,
                "width": width,
                "height": height,
                "orientation": int(orientation),
                "pts": pts.tolist(),
            }

            tiles.append(tile_info)

        convert_pos_coords(tiles)
        for tile in tiles:
            # these variables need to be reassigned because python's variable scope lets the variables from the previous for loop out
            id = tile["id"]
            orientation = tile["orientation"]
            x_pos = tile["x_pos"]
            y_pos = tile["y_pos"]
            x_coord = tile["x_coord"]
            y_coord = tile["y_coord"]
            pts = np.array(tile["pts"])

            # Draw visual feedback on frame
            cv2.polylines(frame, [pts.astype(int)], True, (0, 255, 0), 2)
            cv2.circle(frame, (x_pos, y_pos), 4, (0, 0, 255), -1)
            cv2.putText(
                frame,
                f"ID: {id}",
                (x_pos - 30, y_pos - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                2,
            )

            cv2.putText(
                frame,
                f"Deg: {int(orientation)}",
                (x_pos - 30, y_pos - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 255),
                2,
            )

            cv2.putText(
                frame,
                f"X: {x_coord}",
                (x_pos - 30, y_pos + 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 0, 255),
                2,
            )

            cv2.putText(
                frame,
                f"Y: {y_coord}",
                (x_pos - 30, y_pos + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                2,
            )

    # Clean output JSON representation of the current layout
    json_output = json.dumps({"tile": len(tiles), "tiles": tiles})

    print(json_output)
    print(board_matrix(tiles))
    sender.send(json_output)

    cv2.imshow("Shape Detection", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

sender.stop()
cap.release()
cv2.destroyAllWindows()
