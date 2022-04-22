import logging

from django import template
from django.conf import settings
from django.forms.utils import flatatt
from django.utils.safestring import mark_safe

from wagtail.images.templatetags.wagtailimages_tags import image as wagtail_image_tag, allowed_filter_pattern
from libthumbor import CryptoURL

register = template.Library()

crypto = CryptoURL(key=settings.THUMBOR_SECURITY_KEY)

logger = logging.getLogger('django')

class ThumbifyImageNode(template.Node):
    def __init__(self, image_expr, filter_spec, output_var_name=None, attrs={}):
        self.image_expr = image_expr
        self.output_var_name = output_var_name
        self.attrs = attrs
        self.filter_spec = filter_spec

    def render(self, context):
        try:
            image = self.image_expr.resolve(context)
        except template.VariableDoesNotExist:
            return ''

        if not image:
            if self.output_var_name:
                context[self.output_var_name] = None
            return ''

        if hasattr(context, 'request'):
            url = context.request.build_absolute_uri(image.get_rendition('original').url)
        elif (context.get('request')):
            url = context['request'].build_absolute_uri(image.get_rendition('original').url)
        else:
            url = image.get_rendition('original').url

        if settings.THUMBOR_IMAGE_URL_REPLACEMENT:
            url = url.replace(settings.THUMBOR_IMAGE_URL_REPLACEMENT[0], settings.THUMBOR_IMAGE_URL_REPLACEMENT[1])

        kwargs = {
            'image_url': url,
            'smart': True,
        }

        for filter in self.filter_spec:
            filter_parts = filter.split('-')

            if filter_parts[0] == 'width':
                kwargs.update({'width': filter_parts[1]})

            if filter_parts[0] == 'height':
                kwargs.update({'height': filter_parts[1]})

            if filter_parts[0] == 'fill':
                width, height = filter_parts[1].split('x')
                kwargs.update({'width': width})
                kwargs.update({'height': height})
                kwargs.update({'fit_in': False})

        thumbor_url = crypto.generate(**kwargs)

        image_url = settings.THUMBOR_SERVER + thumbor_url

        if self.output_var_name:
            context[self.output_var_name] = {'url': image_url}
            return ''
        else:
            resolved_attrs = {}
            for key in self.attrs:
                resolved_attrs[key] = self.attrs[key].resolve(context)

            resolved_attrs.update({
                'alt': image.default_alt_text,
            })

            return mark_safe('<img src="{}"{}>'.format(image_url, flatatt(resolved_attrs)))


@register.tag(name='thumbify')
def image(parser, token):
    if settings.THUMBOR_USE and settings.THUMBOR_SECURITY_KEY and settings.THUMBOR_SERVER:
        bits = token.split_contents()[1:]
        image_expr = parser.compile_filter(bits[0])
        bits = bits[1:]

        filter_specs = []
        attrs = {}
        output_var_name = None

        as_context = False  # if True, the next bit to be read is the output variable name
        is_valid = True

        for bit in bits:
            if bit == 'as':
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
                    name, value = bit.split('=')
                    attrs[name] = parser.compile_filter(value)  # setup to resolve context variables as value
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
            return ThumbifyImageNode(image_expr, filter_specs, attrs=attrs, output_var_name=output_var_name)
        else:
            raise template.TemplateSyntaxError(
                "'image' tag should be of the form {% image self.photo max-320x200 [ custom-attr=\"value\" ... ] %} "
                "or {% image self.photo max-320x200 as img %}"
            )


    else:
        return wagtail_image_tag(parser, token)
