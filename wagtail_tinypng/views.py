""""wagtailtinypng views."""
import tempfile
import os
import tinify

from django.conf import settings
from django.core.files.base import ContentFile
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.views.generic import TemplateView
from wagtail.images.models import Image

from .models import WagtailTinyPNGImage
from .templatetags.wagtail_tinypng import allowable_image_type


class TinifyPNG(TemplateView):
    http_method_names = ["get", "post"]

    def post(self, request, *args, **kwargs):
        tinify.key = settings.TINIFY_API_KEY
        image_id = kwargs["pk"]
        image_url = reverse("wagtailimages:edit", args=(image_id,))
        image, created = WagtailTinyPNGImage.objects.get_or_create(
            wagtail_image_id=image_id
        )
        original_image = image.wagtail_image

        if not allowable_image_type(original_image):
            messages.error(request, "Image type not supported for compression.")
            return redirect(image_url)

        try:
            image.original_size = original_image.file.size

            # Descargar la imagen a un archivo temporal
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(original_image.file.read())
                temp_file_path = temp_file.name

            # Procesar la imagen con TinyPNG
            source = tinify.from_file(temp_file_path)
            resize_width = None
            resize_height = None

            if getattr(settings, "TINIFY_MAX_WIDTH", None):
                try:
                    resize_width = int(settings.TINIFY_MAX_WIDTH)
                except ValueError:
                    pass

                if resize_width:
                    resized = source.resize(method="scale", width=resize_width)
                    resized.to_file(temp_file_path)
            elif getattr(settings, "TINIFY_MAX_HEIGHT", None):
                try:
                    resize_height = int(settings.TINIFY_MAX_HEIGHT)
                except ValueError:
                    pass

                if resize_height:
                    resized = source.resize(method="scale", height=resize_height)
                    resized.to_file(temp_file_path)
            else:
                source.to_file(temp_file_path)

            # Subir la imagen procesada de vuelta a S3
            with open(temp_file_path, 'rb') as f:
                original_image.file.save(original_image.file.name, ContentFile(f.read()), save=True)

            # Actualizar los metadatos de la imagen
            image.minified_size = original_image.file.size
            original_image.file_size = original_image.file.size
            image.date_minified = timezone.now()
            image.save()

            original_image.height = original_image.file.height
            original_image.width = original_image.file.width
            original_image.save()

            original_image.renditions.all().delete()

            percent = 100 - round(image.minified_size / image.original_size * 100)
            messages.success(
                request,
                "Image minified. You've saved {}%! You have used {} compressions this month.".format(
                    percent, tinify.compression_count
                ),
            )

            # Eliminar el archivo temporal
            os.unlink(temp_file_path)

        except tinify.AccountError as e:
            messages.warning(request, f"TinyPNG account error. {str(e)}")
        except tinify.ServerError as e:
            messages.error(request, f"TinyPNG.com server error. {str(e)}")
        except tinify.ConnectionError as e:
            messages.error(request, f"TinyPNG.com connection error. {str(e)}")
        except tinify.ClientError as e:
            messages.warning(request, f"TinyPNG.com connection error. {str(e)}")
        except tinify.Error as e:
            messages.error(request, f"Compression error. {str(e)}")
        except Exception as e:
            if settings.DEBUG:
                exception_type = type(e)
                print(exception_type)
            messages.error(request, f"Compression error. {str(e)}")

        return redirect(image_url)

    def get(self, request, *args, **kwargs):
        """If GET request, redirect back to the image edit page."""
        image_url = reverse("wagtailimages:edit", args=(kwargs["pk"],))
        return redirect(image_url)
