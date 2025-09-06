# Image Labeling App 🖼️

A Python-based application for **image labeling**, designed to streamline the process of creating bounding box annotations in the **YOLO format**. This tool allows you to draw, move, resize, and delete rectangles on images, assign tags to them, and manage your annotations with robust **undo/redo** functionality.

---

## Features

* **Image Loading**: Supports common image formats (JPG, PNG, BMP).
* **Interactive Labeling**: Draw, move, and resize bounding boxes directly on the image.
* **YOLO Format Support**: Annotations are stored and exported in the standard YOLO format (`cx`, `cy`, `w`, `h` normalized coordinates).
* **Tagging**: Assign predefined or custom tags to bounding boxes.
* **Undo/Redo**: Extensive undo/redo history to safely manage your annotations.
* **Batch Processing**: Load and annotate multiple images from a directory.
* **Visual Feedback**: Clear highlighting of selected boxes and interactive handles.

---

## Getting Started

### Prerequisites

* **Python 3**: Ensure you have Python 3 installed on your system.
* **Pillow Library**: For image manipulation. Install it using pip:
    ```bash
    pip install Pillow
    ```

### Installation

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

### Running the Application

1.  **Open a Folder**:
    * Launch the application by running `python Fixing Labeling App.py` (or the name of your main script).
    * From the menu bar, select **File > Open Folder**.
    * Choose the directory containing the images you want to label.

2.  **Labeling Images**:
    * Images from the selected folder will appear in the list on the right. Click an image to load it into the canvas.
    * **To Draw a Rectangle**: Click and drag on the image.
    * **To Select/Move a Rectangle**: Click inside an existing rectangle. Drag to move it.
    * **To Resize a Rectangle**: Click and drag one of the corner or edge handles.
    * **To Delete a Rectangle**: Double-click on the rectangle or its handles.
    * **To Change Tag**: Select a rectangle, then choose a tag from the "Tags" list on the left.
    * **Navigation**: Use the **Left/Right arrow keys** to move between images.
    * **Undo/Redo**: Use **Ctrl+Z** (or Cmd+Z on Mac) to undo, and **Ctrl+Y** (or Cmd+Shift+Z on Mac) to redo.

---

## File Structure

* `Fixing Labeling App.py`: The main application script.
* `*.txt` files: Annotation files generated in YOLO format, corresponding to each image.

---

## How Annotations are Stored

For each image (e.g., `image.jpg`), an annotation file (`image.txt`) is created in the same directory.
Each line in the `.txt` file represents one bounding box in the YOLO format: `<class_id> <center_x> <center_y> <width> <height>`


* `<class_id>`: The tag assigned to the object (e.g., "Object", "Person").
* `<center_x>`, `<center_y>`: The normalized center coordinates of the bounding box (ranging from 0 to 1).
* `<width>`, `<height>`: The normalized width and height of the bounding box (ranging from 0 to 1).

---

## Contributing

Contributions are welcome! If you have suggestions for improvements or new features, feel free to open an issue or submit a pull request.

---

## License

This project is licensed under the [MIT License] (you might want to add a LICENSE file with the MIT license text).
