import json
import math
import numpy as np
import cv2
import cv2.aruco as aruco
from tcp_sender import JsonTcpSender

TILE_MARKER_RATIO = 1 / 1
FLIPX = False
FLIPY = False

sender = JsonTcpSender("127.0.0.1", 5005)


def normalize_board(tiles: list):
    """Manipulates the list and adds normalized orientation, x_pos, and y_pos to
    each tile base on a reference tile with an id of 0. This reference tile will
    be removed from the list after the normalization has occured."""

    if len(tiles) == 0:
        return

    tiles.sort(key=lambda tile: tile["id"])
    if tiles[0]["id"] != 0:
        print("reference marker not found")
        # this only exists so that the program doesn't crash and isnt used otherwise
        for tile in tiles:
            tile["orientation_norm"] = tile["orientation"]
            tile["x_pos_norm"] = tile["x_pos"]
            tile["y_pos_norm"] = tile["y_pos"]
        return

    # instantiate ref_tile and attributes
    ref_tile = tiles[0]
    ref_tile["orientation_norm"] = 0
    ref_tile["x_pos_norm"] = 0
    ref_tile["y_pos_norm"] = 0

    ref_orientation = ref_tile["orientation"]
    ref_x_pos = ref_tile["x_pos"]
    ref_y_pos = ref_tile["y_pos"]

    # Pre-calculate sine and cosine of the reference frame's orientation
    cos_theta = math.cos(-ref_orientation)
    sin_theta = math.sin(-ref_orientation)

    for tile in tiles[1:]:
        tile["orientation_norm"] = tile["orientation"] - ref_orientation

        # Get raw distance offsets relative to the origin marker
        dx = tile["x_pos"] - ref_x_pos
        dy = tile["y_pos"] - ref_y_pos

        # Rotate the camera coordinate space into the reference marker's frame
        tile["x_pos_norm"] = dx * cos_theta - dy * sin_theta
        tile["y_pos_norm"] = dx * sin_theta + dy * cos_theta

    tiles.pop(0)


def convert_pos_coords(tiles: list, flipx: bool = False, flipy: bool = False):
    """Manipulates the list, tiles, to add the x and y coordinate values so that the tiles can be easily mapped to a grid."""

    # empty case
    if len(tiles) == 0:
        return np.zeros((0, 0), dtype=int)

    width_median = np.median(np.array([tile["width"] for tile in tiles]))
    width_tolerance = width_median * 0.2

    tiles = sorted(tiles, key=lambda tile: tile["x_pos_norm"])

    # Bin similar x values
    x_bins = []

    for tile in tiles:
        x_pos_norm = tile["x_pos_norm"]

        # Create first bin
        if len(x_bins) == 0:
            x_bins.append([x_pos_norm])
        elif abs(x_pos_norm - np.mean(x_bins[-1])) < width_tolerance:
            x_bins[-1].append(x_pos_norm)
        else:
            x_bins.append([x_pos_norm])

    # Calculate the average position of each group
    x_bin_means = [np.mean(group) for group in x_bins]

    # Map actual X positions to grid coordinates
    x_pos_norm_coords = {}

    for i, bin in enumerate(x_bins):
        if i == 0:
            coord = 0
        else:
            # Sets the coord to be the previous groups coord + the number of tile widths apart from the previous group
            mean_distance = x_bin_means[i] - x_bin_means[i - 1]
            coord = (
                round(mean_distance / width_median)
                + x_pos_norm_coords[x_bins[i - 1][0]]
            )

        for x_pos_norm in bin:
            x_pos_norm_coords[x_pos_norm] = coord

    # Repeat the same steps with y values
    height_median = np.median(np.array([tile["height"] for tile in tiles]))
    height_tolerance = height_median * 0.2

    # Bin similar Y values.
    # Sort by Y independently of the X ordering.
    y_values = sorted(tile["y_pos_norm"] for tile in tiles)

    y_bins = []

    for y_pos_norm in y_values:
        # Create the first bin
        if len(y_bins) == 0:
            y_bins.append([y_pos_norm])
        elif abs(y_pos_norm - np.mean(y_bins[-1])) < height_tolerance:
            y_bins[-1].append(y_pos_norm)
        else:
            y_bins.append([y_pos_norm])

    # Calculate the average position of each group
    y_bin_means = [np.mean(group) for group in y_bins]

    # Map actual Y positions to grid coordinates
    y_pos_norm_coords = {}

    for i, bin_values in enumerate(y_bins):
        if i == 0:
            coord = 0
        else:
            # Distance between adjacent rows, measured in tile heights
            mean_distance = y_bin_means[i] - y_bin_means[i - 1]
            coord = (
                round(mean_distance / height_median)
                + y_pos_norm_coords[y_bins[i - 1][0]]
            )

        for y_pos_norm in bin_values:
            y_pos_norm_coords[y_pos_norm] = coord

    for tile in tiles:
        x_pos_norm = tile["x_pos_norm"]
        y_pos_norm = tile["y_pos_norm"]
        tile["x_coord"] = x_pos_norm_coords[x_pos_norm]
        tile["y_coord"] = y_pos_norm_coords[y_pos_norm]

    if flipx:
        x_coord_max = max(tile["x_coord"] for tile in tiles)
        for tile in tiles:
            tile["x_coord"] = x_coord_max - tile["x_coord"]

    if flipy:
        y_coord_max = max(tile["y_coord"] for tile in tiles)
        for tile in tiles:
            tile["y_coord"] = y_coord_max - tile["y_coord"]


def board_matrix(tiles: list, flipx: bool = False, flipy: bool = False):
    """Returns a 2D matrix representation of the board."""

    if len(tiles) == 0:
        return ""

    # Find the coordinate bounds
    min_x = min(tile["x_coord"] for tile in tiles)
    max_x = max(tile["x_coord"] for tile in tiles)
    min_y = min(tile["y_coord"] for tile in tiles)
    max_y = max(tile["y_coord"] for tile in tiles)

    # Shift coordinates so the smallest X and Y are zero
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    matrix = np.full((height, width), " ", dtype=object)

    for tile in tiles:
        x = tile["x_coord"] - min_x
        y = tile["y_coord"] - min_y

        if flipx:
            x = width - 1 - x

        if flipy:
            y = height - 1 - y

        matrix[y, x] = tile["id"]

    return matrix


# 1. Load your camera calibration data (Required for accurate 3D orientation)
camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=float)
dist_coeffs = np.zeros((5, 1))

# Initiate TCP Connection
sender.start()

# 2. Initialize video capture and ArUco parameters
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
fps = cap.get(cv2.CAP_PROP_FPS)

# Match this to the dictionary you selected online
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
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
            width = int(marker_width * TILE_MARKER_RATIO)
            height = int(marker_height * TILE_MARKER_RATIO)
            dx = topRight[0] - topLeft[0]
            dy = topRight[1] - topLeft[1]
            orientation = math.atan2(dy, dx)  # in radians

            tile_info = {
                "id": int(id),
                "x_pos": x,
                "y_pos": y,
                "width": width,
                "height": height,
                "orientation": orientation,
                "pts": pts.tolist(),  # can't be converted to json as a numpy array
            }

            tiles.append(tile_info)

        normalize_board(tiles)
        convert_pos_coords(tiles, flipy=FLIPY)

        for tile in tiles:
            # convert orientation_ into degrees rounded to multiples of 90
            tile["orienation"] = math.degrees(tile["orientation"])
            tile["orientation_norm"] = (
                round(math.degrees(tile["orientation_norm"]) / 90.0) * 90
            )

            # these variables need to be reassigned because python's variable scope lets the variables from the previous for loop out
            x_pos = tile["x_pos"]
            y_pos = tile["y_pos"]
            width = tile["width"]
            height = tile["height"]
            pts = np.array(tile["pts"])

            attributes = ["id", "orientation_norm", "x_coord", "y_coord"]

            # Draw visual feedback on frame
            cv2.polylines(frame, [pts.astype(int)], True, (0, 255, 0), 2)
            cv2.circle(frame, (x_pos, y_pos), 4, (255, 0, 0), -1)

            for i, attribute in enumerate(attributes):
                cv2.putText(
                    frame,
                    f"{attribute}: {tile[attribute]}",
                    (
                        int((max(0, x_pos - (width * 0.4)))),
                        int(max(0, y_pos - (height * 0.3) + (i * 15))),
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),
                    2,
                )

    # Clean output JSON representation of the current layout
    json_output = json.dumps({"tile": len(tiles), "tiles": tiles})

    sender.send(json_output)
    print(json_output)
    print(board_matrix(tiles, flipx=FLIPX, flipy=FLIPY))

    cv2.imshow("Shape Detection", frame)

    # Press Q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

sender.stop()
cap.release()
cv2.destroyAllWindows()
