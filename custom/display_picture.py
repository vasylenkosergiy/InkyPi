# display_image.py
#   Intelligently crop and scale supplied image
#   and then display on e-ink display.

import argparse
import sys

from PIL import Image

# cv2, numpy та inky імпортуються лише коли справді потрібні (не для --weather),
# див. блок нижче в __main__.

 

import epd7in3e

import weather_picture


def load_image(image_path):
    return cv2.imread(image_path)

def save_image(image_path, image):
    cv2.imwrite(image_path, image)

def pil_to_cv(pil_image):
    # PIL (RGB) -> OpenCV (BGR), без запису у файл
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)

def cv_to_pil(image):
    # OpenCV (BGR) -> PIL (RGB)
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

def crop(image, disp_w, disp_h, intelligent=True):
    # Intelligently resize and crop image to display proportions.
    # Largest crop shifted towards maximum saliency. 

    img_h, img_w, img_c = image.shape
    print(f"Input WxH: {img_w} x {img_h}")

    img_aspect = img_w / img_h
    disp_aspect = disp_w / disp_h

    print(f"Image aspect ratio {img_aspect} ({img_w} x {img_h})")
    print(f"Display aspect ratio {disp_aspect} ({disp_w} x {disp_h})")

    if img_aspect < disp_aspect:
        # scale width, crop height.
        resize = (disp_w, int(disp_w / img_aspect))
    else:
        # scale height, crop width
        resize = (int(disp_h * img_aspect), disp_h)

    print(f"Resizing to {resize}")
    image = cv2.resize(image, resize)
    img_h, img_w, img_c = image.shape

    # Cropping
    x_off = int((img_w - disp_w) / 2)
    y_off = int((img_h - disp_h) / 2)
    assert x_off == 0 or y_off == 0, "My logic is broken"

    if intelligent:

        # Initialize OpenCV's static saliency spectral residual detector and
        # compute the saliency map
        saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
        (success, saliencyMap) = saliency.computeSaliency(image)
        saliencyMap = (saliencyMap * 255).astype("uint8")

        if not x_off:
            # Cropping height
            vert = np.max(saliencyMap, axis=1)
            vert = np.convolve(vert, np.ones(64)/64, "same")
             
            sal_centre = int(np.argmax(vert))
            img_centre = int(img_h / 2)
            shift_y = max(min(sal_centre - img_centre, y_off), -y_off)
            y_off += shift_y
        else:
            # Cropping width
            horiz = np.max(saliencyMap, axis=0)
            horiz  = np.convolve(horiz, np.ones(64)/64, "same")
            sal_centre = int(np.argmax(horiz))
            img_centre = int(img_w / 2)
            shift_x = max(min(sal_centre - img_centre, x_off), -x_off)
            x_off += shift_x

    image = image[y_off:y_off + disp_h,
                  x_off:x_off + disp_w]

    img_h, img_w, img_c = image.shape
    print(f"Cropped WxH: {img_w} x {img_h}")
    return image


def display_waveshare(img, resize=True):
    # img — PIL.Image, без проміжного файлу
    epd = epd7in3e.EPD()
    if resize:
        img = img.resize((epd.width, epd.height))
    elif img.size != (epd.width, epd.height):
        raise ValueError(f"Розмір картинки {img.size} не збігається з дисплеєм "
                         f"{(epd.width, epd.height)}")

    epd.init()
    epd.Clear()
    epd.display(epd.getbuffer(img))
    epd.sleep()
    

if __name__ == "__main__":

    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=None,
        help="input image (не потрібно з --weather)")
    ap.add_argument("-w", "--weather", action="store_true", default=False,
        help="взяти картинку з weather_picture.py напряму, без файлу")
    ap.add_argument("-o", "--output", default="",
        help="name to save cropped display image if provided")
    ap.add_argument("-p", "--portrait", action="store_true",
                    default=False, help="Portrait orientation")
    ap.add_argument("-c", "--centre_crop", action="store_true",
                    default=False, help="Simple centre cropping")
    ap.add_argument("-r", "--resize_only", action="store_true",
                    default=False, help="Simply resize image to display ignoring aspect ratio")
    ap.add_argument("-s", "--simulate_display", action="store_true",
                    default=False, help="Do not interact with e-paper display to get resolution")
    ap.add_argument("--width", type=int, default=800, help="The width of the display")
    ap.add_argument("--height", type=int, default=480, help="The height of the display")
    args = vars(ap.parse_args())

    if not args["weather"] and not args["image"]:
        ap.error("вкажіть файл картинки або використайте --weather")

    simulate_display = args["simulate_display"]

    # Погода: картинка вже потрібного розміру — без кропу, ресайзу та Inky
    if args["weather"]:
        img = weather_picture.create_picture()
        print(f"Weather picture: {img.size[0]} x {img.size[1]}")
        if args["output"]:
            img.save(args["output"], "PNG")
        if not simulate_display:
            display_waveshare(img, resize=False)
        sys.exit(0)

    # Далі потрібні OpenCV, numpy та Inky (тільки для звичайних картинок)
    import cv2
    import numpy as np
    from inky.auto import auto

    disp_w, disp_h = args["width"], args["height"]

    # Get resolution from Inky
    if not simulate_display:
        inky = auto(ask_user=True, verbose=True)
        disp_w, disp_h = inky.resolution

    # Swap axes for portrait orientation
    if args["portrait"]:
        disp_w, disp_h = disp_h, disp_w

    image = load_image(args["image"])

    if args["resize_only"]:
        print(f"Resizing to {disp_w}x{disp_h}")
        image = cv2.resize(image, (disp_w, disp_h))
    else:
        image = crop(image, disp_w, disp_h, args["centre_crop"]==False)

    if not simulate_display:
        display_waveshare(cv_to_pil(image))

    if args["output"]:
        save_image(args["output"], image)
