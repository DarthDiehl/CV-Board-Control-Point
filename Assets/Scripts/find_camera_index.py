import cv2

camera_indices = [0, 1, 2, 3, 4]
caps = {}

for index in camera_indices:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if cap.isOpened():
        print(f"Found camera index {index}")
        caps[index] = cap
    else:
        cap.release()

if not caps:
    print("No cameras were found")
    exit()

print("\nCams are up. Press 'q' to exit.")

# 2. Main loop to display the live feeds
while True:
    for index, cap in caps.items():
        ret, frame = cap.read()
        
        if ret:
            cv2.imshow(f"Camera Index {index}", frame)
        else:
            print(f"Failed to grab frame from Camera {index}")

    # 3. Check for the 'q' key to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

for cap in caps.values():
    cap.release()

cv2.destroyAllWindows()
print("Closed all camera feeds")