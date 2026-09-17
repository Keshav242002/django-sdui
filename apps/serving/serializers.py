from rest_framework import serializers


class ScreenRequestSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=["android", "ios"], required=False)
    app_version = serializers.CharField(required=False, default="0.0.0")
    fund_id = serializers.CharField(required=False, allow_blank=True)


class WidgetRequestSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    fund_id = serializers.CharField(required=False, allow_blank=True)
