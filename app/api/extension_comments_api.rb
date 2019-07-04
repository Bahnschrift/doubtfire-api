require 'grape'

module Api
  class ExtensionCommentsApi < Grape::API
    helpers AuthenticationHelpers
    helpers AuthorisationHelpers
    
    desc 'Request an extension for a task'
    params do
      requires :comment, type: String, desc: 'The details of the request'
    end
    post '/projects/:project_id/task_def_id/:task_definition_id/extension' do
      project = Project.find(params[:project_id])
      task_definition = project.unit.task_definitions.find(params[:task_definition_id])
      task = project.task_for_task_definition(task_definition)

      unless authorise? current_user, task, :request_extension
        error!({ error: 'Not authorised to request an extension for this task' }, 403)
      end

      result = task.apply_for_extension(current_user, params[:comment])
      result.serialize(current_user)
    end

    desc 'Assess an extension for a task'
    params do
      requires :granted, type: Boolean, desc: 'Assess an extension'
    end
    put '/projects/:project_id/task_def_id/:task_definition_id/assess_extension/:task_comment_id' do
      project = Project.find(params[:project_id])
      task_definition = project.unit.task_definitions.find(params[:task_definition_id])
      task = project.task_for_task_definition(task_definition)

      unless authorise? current_user, task, :assess_extension
        error!({ error: 'Not authorised to assess an extension for this task' }, 403)
      end

      task_comment = task.all_comments.find(params[:task_comment_id]).becomes(ExtensionComment)

      unless task_comment.assess_extension(current_user, params[:granted])
        if task_comment.errors.count >= 1
          error!({error: task_comment.errors.full_messages.first}, 403)
        else
          error!({error: 'Error saving extension'}, 403)
        end
      end
      task_comment.serialize(current_user)
    end

  end
end
