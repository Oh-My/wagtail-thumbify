import logging

from django import template
from django.conf import settings
from django.forms.utils import flatatt
from django.utils.safestring import mark_safe, SafeString

from wagtail.images.templatetags.wagtailimages_tags import (
    image as wagtail_image_tag,
)
from wagtail.images.models import Image as WagtailImage
from wagtail.images.models import Filter
from libthumbor import CryptoURL
import re
from wagtail.images.models import Rendition
from PIL import Image
from tempfile import NamedTemporaryFile
import requests
from pathlib import Path
import os
import hashlib
import urllib.parse

register = template.Library()

crypto = CryptoURL(key=settings.THUMBOR_SECURITY_KEY)

logger = logging.getLogger("django")

allowed_filter_pattern = Filter.spec_pattern


class ThumbifyImageNode(template.Node):
    thumbor_filters_map = {
        "brightness": "brightness",
        "background_color": "background_color",
        "blur": "blur",
        "contrast": "contrast",
        "convolution": "convolution",
        "cover": "cover",
        "equalize": "equalize",
        #'fill': 'fill',
        "focal": "focal",
        #'format': 'format',
        "grayscale": "grayscale",
        "max_bytes": "max_bytes",
        "no_upscale": "no_upscale",
        "proportion": "proportion",
        "quality": "quality",
        "rgb": "rgb",
        "rotate": "rotate",
        "round_corner": "round_corner",
        "saturation": "saturation",
        "sharpen": "sharpen",
        "stretch": "stretch",
        "strip_exif": "strip\\_exif",
        "strip_icc": "strip\\_icc",
        "upscale": "upsacle",
        "watermark": "watermark",
    }

    def __init__(self, image_expr, filter_spec, output_var_name=None, attrs={}):
        self.image_expr = image_expr
        self.output_var_name = output_var_name
        self.attrs = attrs
        self.filter_spec = filter_spec

    def render(self, context):
        try:
            image = self.image_expr.resolve(context)
        except template.VariableDoesNotExist:
            return ""

        if not image:
            if self.output_var_name:
                context[self.output_var_name] = None
            return ""

        alt_text = None
        filter_kwargs = self.get_filter_kwargs()

        if (
            settings.THUMBOR_USE
            and settings.THUMBOR_SECURITY_KEY
            and settings.THUMBOR_SERVER
        ):
            if type(image) == SafeString:
                image_url = str(image)
            elif type(image) == str:
                image_url = image
            else:
                image_url = image.get_rendition("original").url
                alt_text = image.default_alt_text

            # Try to get absolute url if image_url does not start with http(s)
            if not re.match(r"^https?://", image_url):
                if hasattr(context, "request"):
                    image_url = context.request.build_absolute_uri(image_url)
                elif context.get("request"):
                    image_url = context["request"].build_absolute_uri(image_url)

            if getattr(settings, "THUMBOR_IMAGE_URL_REPLACEMENT", False):
                image_url = image_url.replace(
                    settings.THUMBOR_IMAGE_URL_REPLACEMENT[0],
                    settings.THUMBOR_IMAGE_URL_REPLACEMENT[1],
                )

            if getattr(settings, "THUMBOR_QUOTE_URL", False):
                image_url = urllib.parse.quote(image_url)

            filter_kwargs.update(
                {
                    "image_url": image_url,
                    "smart": True,
                }
            )

            thumbor_url = crypto.generate(**filter_kwargs)
            processed_image_url = settings.THUMBOR_SERVER + thumbor_url
        else:
            # Process image locally
            if type(image) == SafeString:
                original_image = image
            elif type(image) == str:
                original_image = image
            else:
                original_image = image
                alt_text = image.default_alt_text

            processed_image_url = self.process_image(
                image=original_image, **filter_kwargs
            )

        if self.output_var_name:
            context[self.output_var_name] = {"url": processed_image_url}
            return ""
        else:
            resolved_attrs = {}
            for key in self.attrs:
                resolved_attrs[key] = self.attrs[key].resolve(context)

            if alt_text:
                resolved_attrs.update({"alt": alt_text})

            return mark_safe(
                '<img src="{}"{}>'.format(processed_image_url, flatatt(resolved_attrs))
            )

    def get_filter_kwargs(self):
        filter_kwargs = {}

        filters = []

        for filter in self.filter_spec:
            filter_parts = filter.split("-")

            if filter_parts[0] == "width":
                filter_kwargs.update({"width": filter_parts[1]})

            if filter_parts[0] == "height":
                filter_kwargs.update({"height": filter_parts[1]})

            if filter_parts[0] == "fill":
                width, height = filter_parts[1].split("x")
                filter_kwargs.update({"width": width})
                filter_kwargs.update({"height": height})
                filter_kwargs.update({"fit_in": False})

            if filter_parts[0] == "max":
                width, height = filter_parts[1].split("x")
                filter_kwargs.update({"width": width})
                filter_kwargs.update({"height": height})
                filter_kwargs.update({"fit_in": True})

            if filter_parts[0] in self.thumbor_filters_map:
                filter_parts = filter.split("-", maxsplit=1)
                name = filter_parts[0]
                value = None
                if len(filter_parts) > 1:
                    value = filter_parts[1]
                name = self.thumbor_filters_map[filter_parts[0]]

                filters.append("%s(%s)" % (name, value or ""))

        if filters:
            filter_kwargs["filters"] = filters

        return filter_kwargs

    def process_image(self, image, width=None, height=None, fit_in=False):
        if str(width).isnumeric():
            width = int(width)
        if str(height).isnumeric():
            height = int(height)
        if width is None:
            width = 0
        if height is None:
            height = 0

        if type(image) == WagtailImage:
            original_image_path = str(
                Path(settings.MEDIA_ROOT).joinpath(image.file.name)
            )

            stem = Path(original_image_path).stem
            src_hash = str(hashlib.sha1(original_image_path.encode()).hexdigest())
            suffix = Path(original_image_path).suffix
        elif type(image) in [str, SafeString]:
            stem = Path(image).stem
            src_hash = str(hashlib.sha1(image.encode()).hexdigest())
            suffix = Path(image).suffix
        else:
            raise ValueError("Unexpected image value: {}".format(type(image)))

        filter_key = "{}x{}".format(width, height)
        if fit_in:
            filter_key += "_fit_in"

        image_name = "{}_{}_{}{}".format(src_hash, stem, filter_key, suffix)

        resized_dir = (
            Path(settings.MEDIA_ROOT).joinpath("resized").joinpath(src_hash[0:2])
        )
        processed_image_filename = resized_dir.joinpath(image_name)
        processed_image_url = (
            Path(settings.MEDIA_URL)
            .joinpath("resized")
            .joinpath(src_hash[0:2])
            .joinpath(image_name)
        )

        if processed_image_filename.exists():
            return str(processed_image_url)

        with NamedTemporaryFile(mode="wb+") as tmp_image:
            if type(image) == WagtailImage:
                pil_image = Image.open(original_image_path)
            else:
                if not re.match(r"^https?://", image):
                    raise template.TemplateSyntaxError(
                        "Image parameter should be either an image object or an absolute URL"
                    )

                r = requests.get(image, allow_redirects=True)

                tmp_image.write(r.content)
                tmp_image.seek(0)

                pil_image = Image.open(tmp_image)

            resized_dir.mkdir(exist_ok=True, parents=True)

            org_image_ratio = pil_image.width / pil_image.height

            if fit_in:
                # Make image fit in imaginary box
                box_ratio = width / height

                if box_ratio < org_image_ratio:
                    # Use width as guideline using original ratio
                    height = round(width / org_image_ratio)
                else:
                    # Use height as guideline using original ratio
                    width = round(height * org_image_ratio)

                pil_image.thumbnail((width, height))
            else:
                # Keep aspect ratio if one dimension is missing
                if width > 0 and height == 0:
                    height = round(width / org_image_ratio)
                if width == 0 and height > 0:
                    width = round(height * org_image_ratio)

                # First, crop image to a size matching the wanted dimension aspect ratio
                wanted_ratio = width / height

                if wanted_ratio > org_image_ratio:
                    # Use width as guideline using wanted ratio
                    crop_width = pil_image.width
                    crop_height = round(pil_image.width / wanted_ratio)
                else:
                    # Use height as guideline using wanted ratio
                    crop_width = round(pil_image.height * wanted_ratio)
                    crop_height = pil_image.height

                box = (
                    round((pil_image.width - crop_width) / 2),  # left
                    round((pil_image.height - crop_height) / 2),  # upper
                    round((pil_image.width - crop_width) / 2) + crop_width,  # right
                    round((pil_image.height - crop_height) / 2) + crop_height,  # lower
                )

                pil_image = pil_image.crop(box)

                # Then, resize to wanted dimensions
                pil_image = pil_image.resize((width, height))

            pil_image.save(processed_image_filename, quality=85)

        return str(processed_image_url)


@register.tag(name="thumbify")
def image(parser, token):
    bits = token.split_contents()[1:]
    image_expr = parser.compile_filter(bits[0])
    bits = bits[1:]

    filter_specs = []
    attrs = {}
    output_var_name = None

    as_context = False  # if True, the next bit to be read is the output variable name
    is_valid = True

    for bit in bits:
        if bit == "as":
            # token is of the form {% image self.photo max-320x200 as img %}
            as_context = True
        elif as_context:
            if output_var_name is None:
                output_var_name = bit
            else:
                # more than one item exists after 'as' - reject as invalid
                is_valid = False
        else:
            try:
                name, value = bit.split("=")
                attrs[name] = parser.compile_filter(
                    value
                )  # setup to resolve context variables as value
            except ValueError:
                if allowed_filter_pattern.match(bit):
                    filter_specs.append(bit)
                else:
                    raise template.TemplateSyntaxError(
                        "filter specs in 'image' tag may only contain A-Z, a-z, 0-9, dots, hyphens and underscores. "
                        "(given filter: {})".format(bit)
                    )

    if as_context and output_var_name is None:
        # context was introduced but no variable given ...
        is_valid = False

    if output_var_name and attrs:
        # attributes are not valid when using the 'as img' form of the tag
        is_valid = False

    if len(filter_specs) == 0:
        # there must always be at least one filter spec provided
        is_valid = False

    if len(bits) == 0:
        # no resize rule provided eg. {% image page.image %}
        raise template.TemplateSyntaxError(
            "no resize rule provided. "
            "'image' tag should be of the form {% image self.photo max-320x200 [ custom-attr=\"value\" ... ] %} "
            "or {% image self.photo max-320x200 as img %}"
        )

    if is_valid:
        return ThumbifyImageNode(
            image_expr, filter_specs, attrs=attrs, output_var_name=output_var_name
        )
    else:
        raise template.TemplateSyntaxError(
            "'image' tag should be of the form {% image self.photo max-320x200 [ custom-attr=\"value\" ... ] %} "
            "or {% image self.photo max-320x200 as img %}"
        )
