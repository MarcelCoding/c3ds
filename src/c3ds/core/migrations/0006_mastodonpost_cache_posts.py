from django.db import migrations, models


def wrap_post_in_list(apps, schema_editor):
    MastodonPost = apps.get_model('core', 'MastodonPost')
    for post in MastodonPost.objects.all():
        data = post.posts_data
        if isinstance(data, list):
            continue
        post.posts_data = [data] if isinstance(data, dict) else []
        post.save(update_fields=['posts_data'])


def unwrap_first_post(apps, schema_editor):
    MastodonPost = apps.get_model('core', 'MastodonPost')
    for post in MastodonPost.objects.all():
        data = post.posts_data
        post.posts_data = data[0] if isinstance(data, list) and data else None
        post.save(update_fields=['posts_data'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_alter_mastodonpost_hashtags'),
    ]

    operations = [
        migrations.RenameField(
            model_name='mastodonpost',
            old_name='post_data',
            new_name='posts_data',
        ),
        migrations.AlterField(
            model_name='mastodonpost',
            name='posts_data',
            field=models.JSONField(blank=True, default=list, help_text='Cached posts, newest first.',
                                   verbose_name='Posts Data'),
        ),
        migrations.RunPython(wrap_post_in_list, unwrap_first_post),
        migrations.AddField(
            model_name='mastodonpost',
            name='post_count',
            field=models.PositiveIntegerField(default=10, help_text='How many posts to cache and pick from.',
                                              verbose_name='Cached Posts'),
        ),
        migrations.AddField(
            model_name='mastodonpost',
            name='recent_window',
            field=models.PositiveIntegerField(default=180,
                                              help_text='A post younger than this is always shown. (seconds)',
                                              verbose_name='Recent Window'),
        ),
    ]
